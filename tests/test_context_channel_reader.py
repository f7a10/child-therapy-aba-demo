"""Context channel reader: plan moments from local events, send them, write a bound document."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from movement_fixtures import candidate
from test_context_channel_schema import observation


def posture_for(source_sha, tracking_sha, *, decoded_seconds=6.0):
    """Posture reading on the fixture's 0.5 s samples: stand_to_sit between 1.5 and 2.0 s."""
    from aba_demo.posture_features import classify_posture, posture_events

    ratios = [0.6] * 4 + [-0.3] * 8
    samples = [{'time': index * 0.5, 'frame_index': index * 5, 'identity': 'confirmed',
                'state': classify_posture(ratio), 'leg_ratio': ratio}
               for index, ratio in enumerate(ratios)]
    events = [{'event_id': f'pos-{number:06d}', **event, 'clinician_confirmation': 'pending'}
              for number, event in enumerate(posture_events(samples))]
    return {'schema_version': 1, 'kind': 'posture_reading', 'source_sha256': source_sha,
            'tracking_candidate_sha256': tracking_sha,
            'config': {'weights': 'yolo11s-pose.pt', 'keypoint_confidence': 0.5,
                       'standing_min_ratio': 0.4, 'sitting_max_ratio': 0.25,
                       'min_stable_samples': 3, 'max_gap_seconds': 3.0, 'match_iou_min': 0.5},
            'decoded_seconds': decoded_seconds, 'samples': samples, 'events': events}


class FakeReader:
    def __init__(self, path):
        self.read_indices = []

    def read(self, index):
        from PIL import Image

        self.read_indices.append(index)
        return Image.new('RGB', (64, 48), (index % 255, 90, 120))

    def close(self):
        pass


SEGMENTS = [{'start_time': 0.0, 'end_time': 6.0, 'activity': 'table'}]


class FakeAdapter:
    def __init__(self, outcomes=None, activity='table'):
        from aba_demo.context_channel_schema import CONTEXT_TASKS

        self.task = CONTEXT_TASKS[activity]
        self.activity = activity
        self.outcomes = list(outcomes or [])
        self.calls = []

    def analyze(self, frames, *, source_sha256):
        from aba_demo.openrouter_context import OpenRouterContextError

        self.calls.append([frame['time'] for frame in frames])
        outcome = self.outcomes.pop(0) if self.outcomes else 'ok'
        if outcome != 'ok':
            raise OpenRouterContextError(outcome, 'invalid_context:enum'
                                         if outcome == 'provider_response_invalid' else None)
        return {'observation': observation(self.activity),
                'provenance': {'resolved_model': 'deepseek/deepseek-v4.1-flash-0731',
                               'endpoint_provider': 'Wafer'}}


class ContextReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.folder = Path(self.directory.name)
        self.video = self.folder / 'session.mp4'
        self.video.write_bytes(b'authorized-video')
        self.source = hashlib.sha256(b'authorized-video').hexdigest()

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, value):
        path = self.folder / name
        path.write_bytes(json.dumps(value).encode('utf-8'))
        return path

    def inputs(self, **candidate_options):
        tracking = self.write('observations.pending.json',
                              candidate(self.source, **candidate_options))
        tracking_sha = hashlib.sha256(tracking.read_bytes()).hexdigest()
        posture = self.write('posture.pending.json', posture_for(self.source, tracking_sha))
        return tracking, posture

    def read(self, adapter, tracking, posture, output='out', **options):
        from aba_demo.context_channel_reader import read_context

        options.setdefault('max_requests', 4)
        options.setdefault('activity_segments', SEGMENTS)
        adapters = adapter if isinstance(adapter, dict) else {'table': adapter}
        return read_context(self.video, tracking, [posture], self.folder / output, adapters,
                            model='deepseek/deepseek-v4.1-flash', provider='Wafer',
                            frame_reader_factory=FakeReader, sleep=lambda seconds: None,
                            **options)

    def test_moments_come_from_confirmed_samples_inside_each_local_event(self):
        from aba_demo.context_channel_reader import plan_context_moments
        from aba_demo.movement_windows import load_tracking_candidate

        tracking, posture = self.inputs()
        data, _ = load_tracking_candidate(tracking)
        from aba_demo.channel_events import reading_for_document
        events = reading_for_document(json.loads(posture.read_text()), 6.1)['events']
        moments, skipped = plan_context_moments(data, events)
        self.assertEqual(skipped, 0)
        self.assertEqual([(m['moment_id'], m['anchors']) for m in moments],
                         [('ctx-000000', [{'channel': 'posture', 'event_id': 'pos-000000'}])])
        together = events + [{**events[0], 'channel': 'movement', 'event_id': 'lmv-000000',
                              'start_time': 1.0, 'end_time': 2.5, 'detected_time': 3.5}]
        joined, _ = plan_context_moments(data, together)
        self.assertEqual(len(joined), 1)
        self.assertEqual([a['event_id'] for a in joined[0]['anchors']],
                         ['lmv-000000', 'pos-000000'])
        self.assertEqual((joined[0]['start_time'], joined[0]['end_time'],
                          joined[0]['detected_time']), (1.0, 2.5, 3.5))
        self.assertEqual([f['time'] for f in joined[0]['frames']], [1.0, 2.0, 2.5])
        self.assertEqual([f['time'] for f in moments[0]['frames']], [1.5, 2.0])
        self.assertEqual([f['frame_index'] for f in moments[0]['frames']], [15, 20])
        self.assertTrue(all(f['other_boxes'] for f in moments[0]['frames']))
        uncertain_data, _ = load_tracking_candidate(self.inputs(uncertain=range(15, 21))[0])
        self.assertEqual(plan_context_moments(uncertain_data, events), ([], 1))

    def test_reading_writes_a_bound_validated_context_document(self):
        from aba_demo.channel_events import reading_for_document

        tracking, posture = self.inputs()
        adapter = FakeAdapter()
        report = self.read(adapter, tracking, posture)
        self.assertEqual(adapter.calls, [[1.5, 2.0]])
        self.assertEqual((report['moments'], report['read'], report['requests_used']), (1, 1, 1))
        document = json.loads((self.folder / 'out/context_channel.pending.json').read_text(
            encoding='utf-8'))
        self.assertEqual(document['tracking_candidate_sha256'],
                         hashlib.sha256(tracking.read_bytes()).hexdigest())
        reading = reading_for_document(document, 6.1)
        self.assertEqual(reading['events'][0]['details'], observation())
        self.assertEqual(reading['events'][0]['origin'], 'suggested')
        self.assertEqual(document['moments'][0]['activity'], 'table')
        breaks = [{'start_time': 0.0, 'end_time': 1.8, 'activity': 'table'},
                  {'start_time': 1.8, 'end_time': 6.0, 'activity': 'break'}]
        self.read({'break': FakeAdapter(activity='break')}, tracking, posture, output='rest',
                  activity_segments=breaks)
        rest = json.loads((self.folder / 'rest/context_channel.pending.json').read_text(
            encoding='utf-8'))
        self.assertEqual(rest['events'][0]['details'], observation('break'))
        report_file = json.loads((self.folder / 'out/context-report.json').read_text())
        self.assertEqual(report_file['endpoint_providers'], ['Wafer'])
        self.assertNotIn('observation', json.dumps(report_file))

    def test_provider_failures_are_bounded(self):
        from aba_demo.openrouter_context import OpenRouterContextError

        tracking, posture = self.inputs()
        waited = []
        from aba_demo.context_channel_reader import read_context
        report = read_context(self.video, tracking, [posture], self.folder / 'limited',
                              {'table': FakeAdapter(['provider_rate_limited', 'ok'])},
                              activity_segments=SEGMENTS, model='m/x', provider='Wafer', max_requests=4,
                              rate_limit_wait=30, frame_reader_factory=FakeReader,
                              sleep=waited.append)
        self.assertEqual((report['read'], report['requests_used']), (1, 2))
        self.assertIn(30, waited)
        report = self.read(FakeAdapter(['provider_response_invalid'] * 2), tracking, posture,
                           output='invalid')
        self.assertEqual((report['read'], report['unread']), (0, 1))
        self.assertEqual(report['failure_codes'],
                         {'provider_response_invalid:invalid_context:enum': 2})
        with self.assertRaises(OpenRouterContextError):
            self.read(FakeAdapter(['provider_credit_exhausted']), tracking, posture,
                      output='terminal')
        self.assertFalse((self.folder / 'terminal/context_channel.pending.json').exists())

    def test_inputs_and_outputs_are_guarded(self):
        tracking, posture = self.inputs()
        self.read(FakeAdapter(), tracking, posture)
        with self.assertRaisesRegex(ValueError, 'context_candidate_exists'):
            self.read(FakeAdapter(), tracking, posture)
        root = Path(__file__).resolve().parents[1]
        from aba_demo.context_channel_reader import read_context
        with self.assertRaisesRegex(ValueError, 'output_inside_repository'):
            read_context(self.video, tracking, [posture], root / 'tests' / 'no-output',
                         {'table': FakeAdapter()}, activity_segments=SEGMENTS, model='m/x', provider='Wafer', max_requests=2,
                         frame_reader_factory=FakeReader)
        other = self.write('other.json', posture_for('e' * 64, 'f' * 64))
        with self.assertRaisesRegex(ValueError, 'channel_does_not_match_tracking_candidate'):
            self.read(FakeAdapter(), tracking, other, output='other')
        with self.assertRaisesRegex(ValueError, 'invalid_adapter'):
            self.read({'table': FakeAdapter(activity='break')}, tracking, posture, output='wrong')
        with self.assertRaisesRegex(ValueError, 'invalid_activity_segments'):
            self.read(FakeAdapter(), tracking, posture, output='segments',
                      activity_segments=[{'start_time': 0.0, 'end_time': 5.0,
                                          'activity': 'table'}])
        with self.assertRaisesRegex(ValueError, 'request_budget_too_small'):
            self.read(FakeAdapter(), tracking, posture, output='budget', max_requests=0)
        self.video.write_bytes(b'different-video')
        with self.assertRaisesRegex(ValueError, 'video_does_not_match_tracking_candidate'):
            self.read(FakeAdapter(), tracking, posture, output='changed')


    def test_script_plans_without_a_key_and_sends_with_explicit_settings(self):
        import contextlib
        import importlib.util
        import io

        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            'run_context_channel', root / 'scripts' / 'run_context_channel.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        tracking, posture = self.inputs()
        base = ['--video', str(self.video), '--tracking-candidate', str(tracking),
                '--channel', str(posture), '--key-file', str(self.folder / 'missing.env'),
                '--activity', '0:table']
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.assertEqual(script.main(base + ['--plan-only', '--output-dir',
                                                 str(self.folder / 'plan')]), 0)
        self.assertIn('MOMENTS 1', printed.getvalue())
        self.assertFalse((self.folder / 'plan').exists())
        key_file = self.folder / 'local.env'
        key_file.write_text('OPENROUTER_API_KEY=sk-or-test-not-real\n', encoding='utf-8')
        seen = []

        def factory(key, model, provider, reasoning, activity):
            seen.append((model, provider, reasoning, activity))
            return FakeAdapter(activity=activity)

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = script.main(['--video', str(self.video), '--tracking-candidate', str(tracking),
                                '--channel', str(posture), '--key-file', str(key_file),
                                '--output-dir', str(self.folder / 'sent'),
                                '--activity', '0:table', '--activity', '3:movement',
                                '--model', 'deepseek/deepseek-v4.1-flash', '--provider', 'Wafer',
                                '--max-requests', '3', '--min-request-interval', '0'],
                               adapter_factory=factory, frame_reader_factory=FakeReader)
        self.assertEqual(code, 0)
        self.assertEqual(seen, [('deepseek/deepseek-v4.1-flash', 'Wafer',
                                 {'effort': 'low', 'exclude': True}, activity)
                                for activity in ('table', 'movement', 'break')])
        self.assertIn('READ 1', printed.getvalue())
        self.assertNotIn('sk-or-test-not-real', printed.getvalue())

if __name__ == '__main__':
    unittest.main()
