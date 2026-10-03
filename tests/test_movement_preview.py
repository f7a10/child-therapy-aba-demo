"""No-provider movement preview: plan summary, pilot choice, private sheets, labels."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from movement_fixtures import candidate

ROOT = Path(__file__).resolve().parents[1]


def window(number, status, start, end, overlap=None):
    return {'segment_id': f'mov-{number:06d}', 'status': status,
            'start_frame': int(start * 10), 'end_frame': int(end * 10) - 1,
            'start_time': start, 'end_time': end,
            'target_id': None if status == 'identity_uncertain' else 7,
            'max_other_overlap': overlap, 'frames': []}


def planned():
    overlaps = [0.05, 0.1, 0.3, 0.6, 0.15, 0.4, 0.7, 0.25, 0.9, 0.0]
    windows = [window(number, 'eligible', number * 2.0, number * 2.0 + 2.0, overlap)
               for number, overlap in enumerate(overlaps)]
    windows.append(window(10, 'identity_uncertain', 20.0, 21.0))
    windows.append(window(11, 'too_short', 21.0, 21.5, 0.2))
    return windows


class FakeReader:
    instances = []

    def __init__(self, video_path):
        self.requested, self.closed = [], False
        FakeReader.instances.append(self)

    def read(self, index):
        from PIL import Image
        self.requested.append(index)
        return Image.new('RGB', (160, 90), (index * 3 % 256, 90, 140))

    def close(self):
        self.closed = True


class MovementPreviewLogicTests(unittest.TestCase):
    def test_summary_separates_status_time_and_overlap_risk(self):
        from aba_demo.movement_preview import plan_summary

        summary = plan_summary(planned())
        self.assertEqual(summary['status_counts'],
                         {'eligible': 10, 'identity_uncertain': 1, 'too_short': 1})
        self.assertEqual(summary['status_seconds'],
                         {'eligible': 20.0, 'identity_uncertain': 1.0, 'too_short': 0.5})
        self.assertEqual(summary['eligible_overlap'],
                         {'below_0.2': 4, '0.2_to_0.5': 3, 'at_least_0.5': 3})
        self.assertEqual(summary['max_requests_without_retry'], 10)

    def test_pilot_is_deterministic_stratified_and_includes_requested_times(self):
        from aba_demo.movement_preview import select_pilot_windows

        chosen = select_pilot_windows(planned(), count=6, include_times=[7.5])
        self.assertEqual(chosen, select_pilot_windows(planned(), count=6, include_times=[7.5]))
        self.assertEqual(len(chosen), 6)
        self.assertIn('mov-000003', chosen)
        by_id = {w['segment_id']: w for w in planned()}
        self.assertTrue(all(by_id[identifier]['status'] == 'eligible' for identifier in chosen))
        overlaps = [by_id[identifier]['max_other_overlap'] for identifier in chosen]
        self.assertEqual(sum(value < 0.2 for value in overlaps), 2)
        self.assertEqual(sum(0.2 <= value < 0.5 for value in overlaps), 2)
        self.assertEqual(sum(value >= 0.5 for value in overlaps), 2)
        self.assertEqual(chosen, sorted(chosen))
        self.assertEqual(len(select_pilot_windows(planned(), count=40)), 10)
        self.assertNotIn('mov-000010', select_pilot_windows(planned(), include_times=[20.5]))
        with self.assertRaisesRegex(ValueError, 'invalid_pilot_request'):
            select_pilot_windows(planned(), count=0)


class MovementPreviewRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / 'authorized.mp4'
        self.video.write_bytes(b'synthetic-source-not-video')
        self.source_sha = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.candidate = self.root / 'observations.pending.json'
        self.candidate.write_text(json.dumps(candidate(self.source_sha, uncertain={23})),
                                  encoding='utf-8')
        FakeReader.instances = []

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, output, **options):
        from aba_demo.movement_preview import prepare_preview
        return prepare_preview(self.video, self.candidate, output,
                               frame_reader_factory=FakeReader, **options)

    def test_preview_builds_every_eligible_window_without_images_in_json(self):
        output = self.root / 'preview'
        report = self.prepare(output, pilot_count=2)
        reader = FakeReader.instances[0]
        self.assertEqual(reader.requested, sorted(reader.requested))
        self.assertTrue(reader.closed)
        plan = json.loads((output / 'movement-plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['source_sha256'], self.source_sha)
        self.assertEqual(plan['tracking_candidate_sha256'],
                         hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        eligible = [w for w in plan['windows'] if w['status'] == 'eligible']
        self.assertEqual(len(eligible), 4)
        for item in eligible:
            self.assertEqual(len(item['image_sha256']), 2 * len(item['frames']))
            self.assertGreater(item['image_bytes'], 0)
        self.assertNotIn('jpeg', (output / 'movement-plan.json').read_text(encoding='utf-8'))
        self.assertEqual(report['summary']['status_counts'],
                         {'eligible': 4, 'identity_uncertain': 1})
        self.assertEqual(len(report['pilot_segment_ids']), 2)
        for identifier in report['pilot_segment_ids']:
            self.assertTrue((output / 'sheets' / f'{identifier}.png').is_file())
        labels = json.loads((output / 'labels.template.json').read_text(encoding='utf-8'))
        self.assertEqual([item['segment_id'] for item in labels['windows']],
                         report['pilot_segment_ids'])
        self.assertTrue(all(value is None for item in labels['windows']
                            for value in item['labels'].values()))
        self.assertIn('not_determinable', labels['vocabulary']['body_position_change'])
        self.assertEqual(labels['reviewer'], '')

    def test_preview_records_the_crop_mode_and_changes_the_image_hashes(self):
        marked = self.prepare(self.root / 'marked', pilot_count=1,
                              crop_mode='window_stable_others_marked')
        plain = self.prepare(self.root / 'plain', pilot_count=1)
        plans = [json.loads((self.root / name / 'movement-plan.json').read_text(encoding='utf-8'))
                 for name in ('marked', 'plain')]
        self.assertEqual([plan['parameters']['crop_mode'] for plan in plans],
                         ['window_stable_others_marked', 'window_stable'])
        self.assertNotEqual(plans[0]['windows'][0]['image_sha256'],
                            plans[1]['windows'][0]['image_sha256'])
        self.assertEqual(marked['pilot_segment_ids'], plain['pilot_segment_ids'])

    def test_preview_refuses_wrong_video_repository_output_and_overwrite(self):
        other = self.root / 'other.mp4'
        other.write_bytes(b'different')
        from aba_demo.movement_preview import prepare_preview
        with self.assertRaisesRegex(ValueError, 'video_does_not_match_tracking_candidate'):
            prepare_preview(other, self.candidate, self.root / 'x', frame_reader_factory=FakeReader)
        with self.assertRaisesRegex(ValueError, 'output_inside_repository'):
            self.prepare(ROOT / 'tests' / 'movement-preview-must-not-exist')
        self.assertFalse((ROOT / 'tests' / 'movement-preview-must-not-exist').exists())
        self.prepare(self.root / 'once', pilot_count=1)
        with self.assertRaisesRegex(ValueError, 'movement_preview_exists'):
            self.prepare(self.root / 'once', pilot_count=1)


@unittest.skipUnless(importlib.util.find_spec('cv2') and importlib.util.find_spec('numpy'),
                     'OpenCV not installed')
class MovementPreviewScriptTests(unittest.TestCase):
    def test_plan_only_script_uses_no_network_or_provider_module(self):
        import cv2
        import numpy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'synthetic.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
            for index in range(60):
                writer.write(numpy.full((48, 64, 3), index * 4, dtype=numpy.uint8))
            writer.release()
            source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
            candidate_path = root / 'observations.pending.json'
            candidate_path.write_text(json.dumps(candidate(source_sha)), encoding='utf-8')
            guard = (
                'import runpy, socket, sys\n'
                'def blocked(*args, **kwargs):\n'
                '    raise RuntimeError("network_blocked")\n'
                'socket.socket = blocked\n'
                'socket.create_connection = blocked\n'
                f'sys.argv = ["run_movement_reader.py", "--plan-only", "--video", {str(video)!r},'
                f' "--tracking-candidate", {str(candidate_path)!r},'
                f' "--output-dir", {str(root / "out")!r}, "--pilot-count", "2"]\n'
                f'runpy.run_path({str(ROOT / "scripts" / "run_movement_reader.py")!r},'
                ' run_name="__main__")\n'
                'print("PROVIDER_MODULE_LOADED", "aba_demo.openrouter_context" in sys.modules)\n'
            )
            result = subprocess.run([sys.executable, '-c', guard], capture_output=True,
                                    text=True, timeout=120, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("STATUS_COUNTS {'eligible': 3}", result.stdout)
            self.assertIn('PROVIDER_MODULE_LOADED False', result.stdout)
            self.assertNotIn(source_sha, result.stdout)
            self.assertTrue((root / 'out' / 'movement-plan.json').is_file())


@unittest.skipUnless(importlib.util.find_spec('cv2') and importlib.util.find_spec('numpy'),
                     'OpenCV not installed')
class MovementReadScriptTests(unittest.TestCase):
    def test_read_mode_is_bound_to_the_preview_plan_and_never_prints_the_key(self):
        import contextlib
        import io
        import cv2
        import numpy
        from test_movement_reader import FakeAdapter

        spec = importlib.util.spec_from_file_location(
            'run_movement_reader', ROOT / 'scripts' / 'run_movement_reader.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'synthetic.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
            for index in range(60):
                writer.write(numpy.full((48, 64, 3), index * 4, dtype=numpy.uint8))
            writer.release()
            source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
            candidate_path = root / 'observations.pending.json'
            candidate_path.write_text(json.dumps(candidate(source_sha)), encoding='utf-8')
            key_file = root / 'local.env'
            key_file.write_text('OPENROUTER_API_KEY=fixture-secret-key\n', encoding='utf-8')
            common = ['--video', str(video), '--tracking-candidate', str(candidate_path)]
            with contextlib.redirect_stdout(io.StringIO()):
                script.main(['--plan-only', *common, '--output-dir', str(root / 'preview'),
                             '--pilot-count', '2'])
            seen = {}

            def factory(api_key, model, max_tokens):
                seen.update(api_key=api_key, model=model, max_tokens=max_tokens)
                return FakeAdapter()

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = script.main(['--read', *common, '--output-dir', str(root / 'read'),
                                    '--plan', str(root / 'preview' / 'movement-plan.json'),
                                    '--model', 'vendor/model:free', '--max-requests', '3',
                                    '--min-request-interval', '0', '--key-file', str(key_file)],
                                   adapter_factory=factory)
            text = output.getvalue()
            self.assertEqual(code, 0, text)
            self.assertEqual(seen, {'api_key': 'fixture-secret-key',
                                    'model': 'vendor/model:free', 'max_tokens': 8192})
            self.assertIn("STATUS_COUNTS {'analyzed': 2, 'not_requested': 1}", text)
            self.assertIn('REQUESTS_USED 2', text)
            self.assertNotIn('fixture-secret-key', text)
            self.assertTrue((root / 'read' / 'movement.pending.json').is_file())
            with contextlib.redirect_stdout(io.StringIO()) as missing:
                code = script.main(['--read', *common, '--output-dir', str(root / 'none'),
                                    '--plan', str(root / 'preview' / 'movement-plan.json'),
                                    '--model', 'vendor/model:free', '--max-requests', '3',
                                    '--key-file', str(root / 'absent.env')],
                                   adapter_factory=factory)
            self.assertEqual(code, 3)
            self.assertIn('PROVIDER_ERROR provider_not_configured', missing.getvalue())
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                script.main(['--read', *common, '--output-dir', str(root / 'x'),
                             '--plan', str(root / 'preview' / 'movement-plan.json'),
                             '--max-requests', '3'])


if __name__ == '__main__':
    unittest.main()
