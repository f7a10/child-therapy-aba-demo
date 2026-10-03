"""Observation-channel events streamed causally into a live/replay session."""
import json
import tempfile
import unittest
from pathlib import Path

from test_live_session import ALL_FALSE, FakeClock, of_type
from test_session_timeline import two_events

SOURCE = 'a' * 64
TRACKING = 'b' * 64


def feed(**options):
    from aba_demo.live.moments import MomentFeed

    return MomentFeed({'posture': two_events()}, 2.5, source_sha256=SOURCE,
                      tracking_sha256=TRACKING, **options)


class MomentFeedTests(unittest.TestCase):
    def test_events_appear_only_after_they_are_confirmed(self):
        moments = feed()
        posture = two_events()['events']
        first, second = posture[0]['detected_time'], posture[1]['detected_time']
        self.assertEqual(moments.due(first - 0.01), [])
        shown = moments.due(first)
        self.assertEqual([e['entry_id'] for e in shown], ['tl-posture-pos-000000'])
        self.assertEqual(moments.due(first + 0.01), [])  # each event is sent once
        later = moments.due(second)
        self.assertEqual([e['kind'] for e in later], ['sit_to_stand'])
        self.assertEqual((later[0]['origin'], later[0]['details']), ('measured', {}))

    def test_level_follows_the_activity_the_therapist_set_live(self):
        moments = feed()
        moments.set_activity('movement', 1.0)  # before the sit_to_stand ended (2.0)
        entries = moments.due(5.0)
        self.assertEqual([(e['activity'], e['level']) for e in entries],
                         [('table', 'info'), ('movement', 'info')])
        table = feed()
        self.assertEqual([e['level'] for e in table.due(5.0)], ['info', 'flag'])
        late = feed()
        first_entries = late.due(two_events()['events'][1]['end_time'] - 0.1)
        late.set_activity('break', 2.05)  # after the event ended: does not change it
        self.assertEqual([e['level'] for e in first_entries + late.due(5.0)], ['info', 'flag'])

    def test_channels_must_match_the_video_and_tracking(self):
        from aba_demo.live.moments import MomentFeed

        for options in ({'source_sha256': 'c' * 64, 'tracking_sha256': TRACKING},
                        {'source_sha256': SOURCE, 'tracking_sha256': 'c' * 64}):
            with self.subTest(options), self.assertRaisesRegex(ValueError, 'channel_does_not_match'):
                MomentFeed({'posture': two_events()}, 2.5, **options)
        with self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
            MomentFeed({'posture': {**two_events(), 'events': []}}, 2.5,
                       source_sha256=SOURCE, tracking_sha256=TRACKING)
        with self.assertRaisesRegex(ValueError, 'unknown_channel'):
            MomentFeed({'emotion': two_events()}, 2.5, source_sha256=SOURCE,
                       tracking_sha256=TRACKING)


class SessionStreamTests(unittest.TestCase):
    def make(self):
        from aba_demo.live.providers import SyntheticProvider
        from aba_demo.live.session import LiveSession
        from aba_demo.live.source import SyntheticFrameSource

        clock = FakeClock()
        session = LiveSession(SyntheticFrameSource(5, 15),
                              SyntheticProvider([(0, 'confirmed', ALL_FALSE)]), clock=clock,
                              session_id='moments-test', moments=feed())
        session.open()
        session.select_target()
        session.start()
        return session, clock

    def test_session_emits_channel_events_when_due(self):
        session, clock = self.make()
        session.drain_events()
        detected = two_events()['events'][0]['detected_time']
        clock.advance(detected - 0.2)
        session.tick()
        self.assertEqual(of_type(session.drain_events(), 'channel_event'), [])
        clock.advance(0.2)
        session.tick()
        sent = of_type(session.drain_events(), 'channel_event')
        self.assertEqual([e['entry']['entry_id'] for e in sent], ['tl-posture-pos-000000'])
        self.assertLessEqual(sent[0]['entry']['detected_time'], sent[0]['video_time'] + 1e-6)

    def test_activity_changes_reach_the_feed(self):
        session, clock = self.make()
        clock.advance(1.0)
        session.tick()
        session.set_activity('movement')
        clock.advance(2.0)
        session.tick()
        entries = [e['entry'] for e in of_type(session.drain_events(), 'channel_event')]
        self.assertEqual([e['activity'] for e in entries], ['table', 'movement'])
        self.assertEqual(session.snapshot()['channels'], ['posture'])

    def test_sessions_without_channels_are_unchanged(self):
        from aba_demo.live.providers import SyntheticProvider
        from aba_demo.live.session import LiveSession
        from aba_demo.live.source import SyntheticFrameSource

        session = LiveSession(SyntheticFrameSource(5, 5),
                              SyntheticProvider([(0, 'confirmed', ALL_FALSE)]), clock=FakeClock())
        self.assertEqual(session.snapshot()['channels'], [])


class ReplayChannelTests(unittest.TestCase):
    def test_replay_scenario_binds_channel_files_to_its_video_and_tracking(self):
        import hashlib

        from aba_demo.live.scenarios import ReplayScenario
        from movement_fixtures import candidate

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            video = folder / 'session.mp4'
            video.write_bytes(b'authorized-video')
            source = hashlib.sha256(b'authorized-video').hexdigest()
            observations = folder / 'observations.pending.json'
            observations.write_text(json.dumps(candidate(source)), encoding='utf-8')
            tracking = hashlib.sha256(observations.read_bytes()).hexdigest()
            posture = folder / 'posture.json'
            posture.write_text(json.dumps({**two_events(), 'source_sha256': source,
                                           'tracking_candidate_sha256': tracking}),
                               encoding='utf-8')
            scenario = ReplayScenario(video, observations, channels=[posture])
            self.assertEqual(scenario.describe()['channels'], ['posture'])
            self.assertEqual(scenario.build_moments().due(10.0)[0]['channel'], 'posture')
            stranger = folder / 'other.json'
            stranger.write_text(json.dumps(two_events()), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'channel_does_not_match'):
                ReplayScenario(video, observations, channels=[stranger])
            self.assertIsNone(ReplayScenario(video, observations).build_moments())


if __name__ == '__main__':
    unittest.main()
