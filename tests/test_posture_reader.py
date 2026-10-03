"""Local posture reading with fake frames and a fake pose detector."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from movement_fixtures import OTHER_BOX, TARGET_BOX, candidate

ROOT = Path(__file__).resolve().parents[1]


def body(knee_y, box):
    """Keypoints inside ``box``: shoulders at 30%, hips at 50% of its height."""
    x1, y1, x2, y2 = box
    height = y2 - y1
    points = [[x1, y1, 0.0] for _ in range(17)]
    for index, fraction in ((5, 0.3), (6, 0.3), (11, 0.5), (12, 0.5), (13, knee_y), (14, knee_y)):
        points[index] = [(x1 + x2) / 2, y1 + fraction * height, 0.9]
    return points


class FakeReader:
    instances = []

    def __init__(self, video_path):
        self.requested, self.closed = [], False
        FakeReader.instances.append(self)

    def read(self, index):
        from PIL import Image
        self.requested.append(index)
        image = Image.new('RGB', (160, 90))
        image.info['frame_index'] = index
        return image

    def close(self):
        self.closed = True


class FakeDetector:
    """Child stands before frame 30 and sits after; the adult always stands."""

    def __init__(self, *, child_visible=True):
        self.calls = []
        self.child_visible = child_visible

    def detect(self, image):
        index = image.info['frame_index']
        self.calls.append(index)
        child_knee = 0.62 if index < 30 else 0.46
        detections = [{'xyxy': list(OTHER_BOX), 'keypoints': body(0.62, OTHER_BOX)}]
        if self.child_visible:
            detections.append({'xyxy': list(TARGET_BOX), 'keypoints': body(child_knee, TARGET_BOX)})
        return detections


class PostureReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / 'authorized.mp4'
        self.video.write_bytes(b'synthetic-source-not-video')
        self.source_sha = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.candidate = self.root / 'observations.pending.json'
        FakeReader.instances = []

    def tearDown(self):
        self.temp.cleanup()

    def read(self, detector, output='posture', uncertain=(), **options):
        from aba_demo.posture_reader import read_posture
        self.candidate.write_text(json.dumps(candidate(self.source_sha, uncertain=set(uncertain))),
                                  encoding='utf-8')
        return read_posture(self.video, self.candidate, self.root / output,
                            detector=detector, frame_reader_factory=FakeReader, **options)

    def document(self, output='posture'):
        return json.loads((self.root / output / 'posture.pending.json').read_text(encoding='utf-8'))

    def test_reading_writes_a_valid_bound_document_with_one_transition(self):
        from aba_demo.posture_schema import validate_posture_document

        detector = FakeDetector()
        report = self.read(detector, uncertain={50})
        document = validate_posture_document(self.document(), 6.1)
        self.assertEqual(document['source_sha256'], self.source_sha)
        self.assertEqual(document['tracking_candidate_sha256'],
                         hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        self.assertEqual([(e['kind'], e['start_time'], e['end_time']) for e in document['events']],
                         [('stand_to_sit', 2.5, 3.0)])
        self.assertTrue(all(e['clinician_confirmation'] == 'pending' for e in document['events']))
        uncertain = [s for s in document['samples'] if s['identity'] == 'uncertain']
        self.assertEqual([(s['time'], s['state']) for s in uncertain], [(5.0, None)])
        self.assertNotIn(50, detector.calls)
        self.assertEqual(FakeReader.instances[0].requested, sorted(FakeReader.instances[0].requested))
        self.assertTrue(FakeReader.instances[0].closed)
        self.assertEqual(report['event_counts'], {'stand_to_sit': 1})
        self.assertEqual(report['state_counts']['standing'], 6)
        encoded = (self.root / 'posture' / 'posture.pending.json').read_bytes()
        self.assertEqual(report['posture_candidate_sha256'], hashlib.sha256(encoded).hexdigest())

    def test_another_persons_skeleton_is_never_used_for_the_child(self):
        self.read(FakeDetector(child_visible=False))
        states = {s['state'] for s in self.document()['samples'] if s['identity'] == 'confirmed'}
        self.assertEqual(states, {'not_measurable'})
        self.assertEqual(self.document()['events'], [])

    def test_refuses_wrong_video_repository_output_and_overwrite(self):
        from aba_demo.posture_reader import read_posture

        self.read(FakeDetector(), output='once')
        with self.assertRaisesRegex(ValueError, 'posture_candidate_exists'):
            self.read(FakeDetector(), output='once')
        with self.assertRaisesRegex(ValueError, 'output_inside_repository'):
            self.read(FakeDetector(), output=ROOT / 'tests' / 'posture-must-not-exist')
        self.assertFalse((ROOT / 'tests' / 'posture-must-not-exist').exists())
        other = self.root / 'other.mp4'
        other.write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'video_does_not_match_tracking_candidate'):
            read_posture(other, self.candidate, self.root / 'x', detector=FakeDetector(),
                         frame_reader_factory=FakeReader)


class PostureScriptTests(unittest.TestCase):
    def test_script_prints_counts_and_writes_one_evidence_sheet_per_event(self):
        import contextlib
        import importlib.util
        import io

        spec = importlib.util.spec_from_file_location(
            'run_posture_reader', ROOT / 'scripts' / 'run_posture_reader.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'authorized.mp4'
            video.write_bytes(b'synthetic-source-not-video')
            source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
            candidate_path = root / 'observations.pending.json'
            candidate_path.write_text(json.dumps(candidate(source_sha)), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = script.main(['--video', str(video), '--tracking-candidate',
                                    str(candidate_path), '--output-dir', str(root / 'out')],
                                   detector_factory=lambda arguments: FakeDetector(),
                                   frame_reader_factory=FakeReader)
            text = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("EVENT_COUNTS {'stand_to_sit': 1}", text)
            self.assertNotIn(source_sha, text)
            sheets = sorted((root / 'out' / 'evidence').glob('*.png'))
            self.assertEqual([sheet.name for sheet in sheets], ['pos-000000.png'])


if __name__ == '__main__':
    unittest.main()
