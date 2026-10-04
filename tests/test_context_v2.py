"""Context v2 pilot: before/after frame planning, strict answers, local second opinion."""
import json
import unittest
from pathlib import Path

from movement_fixtures import candidate


def moment_frames(data, start_index, end_index):
    time_of = {row['frame_index']: row['time'] for row in data['provenance']['causal_audit']}
    return [{'frame_index': index, 'time': time_of[index]} for index in (start_index, end_index)]


class PlanTests(unittest.TestCase):
    def test_before_and_after_frames_stay_on_the_same_unbroken_binding(self):
        from aba_demo.context_v2 import plan_v2_frames

        data = candidate('a' * 64, decoded=120)  # 10 fps, a sample every 0.5 s
        roles, frames = plan_v2_frames(data, moment_frames(data, 50, 60))
        self.assertEqual(roles, ['before', 'start', 'end', 'after'])
        self.assertEqual([f['time'] for f in frames], [2.0, 5.0, 6.0, 9.0])  # 3 s outside
        self.assertTrue(all(f['other_boxes'] for f in frames))
        # An identity gap between the moment and the BEFORE side drops that frame.
        broken = candidate('a' * 64, decoded=120, uncertain={42})
        roles, frames = plan_v2_frames(broken, moment_frames(broken, 50, 60))
        self.assertEqual(roles, ['start', 'end', 'after'])
        switched = candidate('a' * 64, decoded=120, switch_at=55)
        with self.assertRaisesRegex(ValueError, 'moment_crosses_identity_gap'):
            plan_v2_frames(switched, moment_frames(switched, 50, 60))

    def test_a_child_cut_by_the_frame_edge_is_not_used_before_or_after(self):
        from aba_demo.context_v2 import plan_v2_frames

        data = candidate('a' * 64, decoded=120, target_box=[0.6, 0.2, 1.0, 0.9])
        roles, _ = plan_v2_frames(data, moment_frames(data, 50, 60))
        self.assertEqual(roles, ['start', 'end'])


class AnswerTests(unittest.TestCase):
    def answer(self, **changes):
        value = {'child_separable': 'yes', 'child_location': 'at_table',
                 'child_position_before': 'seated',
                 'child_position_after': 'standing', 'adult_proximity': 'close',
                 'task_materials_near_child': 'present', 'adult_movement_before': 'stayed',
                 'materials_change_before': 'no_change', 'adult_movement_after': 'moved_away',
                 'materials_change_after': 'no_change'}
        value.update(changes)
        return json.dumps({k: v for k, v in value.items() if v is not None})

    def test_only_the_questions_of_the_layout_are_accepted(self):
        from aba_demo.context_v2 import ROLES, task_for

        full, short = task_for(ROLES), task_for(('start', 'end'))
        self.assertEqual(full.parse(self.answer(), [1, 2, 3, 4])['adult_movement_after'],
                         'moved_away')
        self.assertIn('AFTER frame only', full.prompt)
        self.assertIn('MOMENT END frame only', short.prompt)
        self.assertEqual(sorted(short.output_schema(2)['required']),
                         ['adult_proximity', 'child_location', 'child_position_after',
                          'child_position_before', 'child_separable',
                          'task_materials_near_child'])
        self.assertIn('BEFORE frame only', full.prompt)
        self.assertIn('MOMENT START frame only', short.prompt)
        for bad, rule in ((self.answer(adult_movement_after='guided'), 'enum'),
                          (self.answer(materials_change_after=None), 'fields'),
                          (self.answer(child_separable='no'), 'separable'),
                          ('{"a": 1, "a": 2}', 'duplicate_key'), ('{not json', 'json')):
            with self.assertRaisesRegex(ValueError, 'invalid_context:' + rule):
                full.parse(bad, [1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, 'invalid_context_window'):
            full.output_schema(3)
        with self.assertRaisesRegex(ValueError, 'invalid_context_layout'):
            task_for(('before', 'end'))

    def test_no_clinical_or_intent_wording_is_asked(self):
        from aba_demo.context_v2 import LAYOUTS, prompt_for

        for roles in LAYOUTS:
            prompt = prompt_for(roles).lower()
            for word in ('reinforc', 'escape', 'tantrum', 'happy', 'angry', 'attention-seeking'):
                self.assertNotIn(word, prompt)


class SecondOpinionTests(unittest.TestCase):
    def test_the_model_view_after_the_change_is_compared_locally(self):
        from aba_demo.context_v2 import second_opinion

        stood = [('posture', 'sit_to_stand')]
        self.assertEqual(second_opinion(stood, {'child_position_after': 'standing'}), 'agrees')
        self.assertEqual(second_opinion(stood, {'child_position_after': 'seated'}), 'disagrees')
        self.assertEqual(second_opinion(stood, {'child_position_after': 'not_observable'}),
                         'unclear')
        both = [('movement', 'large_movement'), ('posture', 'sit_to_stand')]
        self.assertEqual(second_opinion(both, {'child_position_after': 'walking'}), 'agrees')
        self.assertEqual(second_opinion([('orientation', 'turned_away_from_task')],
                                        {'child_position_after': 'seated'}), 'unclear')
        self.assertEqual(second_opinion(stood, None), 'unclear')
        # The start of the change is checked too: "sat down" while already seated disagrees.
        sat = [('posture', 'stand_to_sit')]
        self.assertEqual(second_opinion(sat, {'child_position_before': 'seated',
                                              'child_position_after': 'seated'}), 'disagrees')
        self.assertEqual(second_opinion(sat, {'child_position_before': 'standing',
                                              'child_position_after': 'seated'}), 'agrees')
        self.assertEqual(second_opinion(stood, {'child_position_before': 'on_floor',
                                                'child_position_after': 'standing'}), 'agrees')



class ReaderTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.folder = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_v2_reading_is_bound_validated_and_feeds_the_timeline(self):
        import hashlib

        from aba_demo.channel_events import reading_for_document
        from aba_demo.context_v2_reader import read_context_v2
        from aba_demo.session_timeline import build_timeline
        from test_context_channel_reader import FakeReader, posture_for

        video = self.folder / 'session.mp4'
        video.write_bytes(b'authorized-video')
        source = hashlib.sha256(b'authorized-video').hexdigest()
        tracking = self.folder / 'observations.pending.json'
        tracking.write_text(json.dumps(candidate(source, decoded=120)), encoding='utf-8')
        tracking_sha = hashlib.sha256(tracking.read_bytes()).hexdigest()
        posture = posture_for(source, tracking_sha, decoded_seconds=12.0)  # stand_to_sit ~1.5-2 s
        posture_path = self.folder / 'posture.pending.json'
        posture_path.write_text(json.dumps(posture), encoding='utf-8')
        asked = []

        class Adapter:
            def __init__(self, task):
                self.task = task

            def analyze(self, frames, *, source_sha256):
                asked.append((self.task.name, len(frames)))
                fields = self.task.output_schema(len(frames))['required']
                answer = {name: 'not_observable' for name in fields}
                answer.update(child_separable='yes', child_location='at_table',
                              child_position_after='seated')
                for name in fields:
                    if name.startswith('adult_movement'):
                        answer[name] = 'moved_away'
                return {'observation': self.task.parse(json.dumps(answer), []),
                        'provenance': {'endpoint_provider': 'Wafer', 'resolved_model': 'm'}}

        segments = [{'start_time': 0.0, 'end_time': 12.0, 'activity': 'table'}]
        plan = read_context_v2(video, tracking, [posture_path], self.folder / 'plan', Adapter,
                               activity_segments=segments, model='m/x', provider='Wafer',
                               max_requests=None, plan_only=True, frame_reader_factory=FakeReader)
        self.assertEqual(plan['moments'], 1)
        report = read_context_v2(video, tracking, [posture_path], self.folder / 'out', Adapter,
                                 activity_segments=segments, model='m/x', provider='Wafer',
                                 max_requests=2, frame_reader_factory=FakeReader,
                                 sleep=lambda seconds: None)
        self.assertEqual((report['read'], report['second_opinions']), (1, {'agrees': 1}))
        raw = (self.folder / 'out' / 'context_channel.pending.json').read_bytes()
        document = json.loads(raw)
        self.assertEqual(document['kind'], 'context_v2_reading')
        reading = reading_for_document(document, 12.1)
        self.assertEqual(reading['channel'], 'context')
        event = reading['events'][0]
        self.assertEqual((event['origin'], event['details']['second_opinion'],
                          event['details']['adult_movement_after']),
                         ('suggested', 'agrees', 'moved_away'))
        self.assertLessEqual(len(event['details']), 10)
        self.assertEqual(asked, [(asked[0][0], len(document['moments'][0]['roles']))])
        timeline = build_timeline({'context': (document, hashlib.sha256(raw).hexdigest())},
                                  segments, 12.1)
        self.assertEqual(len(timeline['entries']), 1)
        tampered = dict(document, moments=[dict(document['moments'][0],
                                                second_opinion='disagrees')])
        with self.assertRaisesRegex(ValueError, 'invalid_context_v2_document'):
            reading_for_document(tampered, 12.1)

if __name__ == '__main__':
    unittest.main()
