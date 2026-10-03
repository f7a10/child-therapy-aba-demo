"""Local large-movement reading with fake frames, a fake pose detector and fake camera."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from movement_fixtures import OTHER_BOX, TARGET_BOX, candidate

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def body(box, shift=0.0):
    """Keypoints inside ``box`` moved right by ``shift``: shoulders 30%, hips 50% down."""
    x1, y1, x2, y2 = box
    height = y2 - y1
    points = [[x1, y1, 0.0] for _ in range(17)]
    for index, fraction in ((5, 0.3), (6, 0.3), (11, 0.5), (12, 0.5)):
        points[index] = [(x1 + x2) / 2 + shift, y1 + fraction * height, 0.9]
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
    """The child shifts right at frame 30; the adult jumps around every frame."""

    def __init__(self, *, child_visible=True):
        self.calls = []
        self.child_visible = child_visible

    def detect(self, image):
        index = image.info['frame_index']
        self.calls.append(index)
        detections = [{'xyxy': list(OTHER_BOX),
                       'keypoints': body(OTHER_BOX, 0.3 * (index % 2))}]
        if self.child_visible:
            detections.append({'xyxy': list(TARGET_BOX),
                               'keypoints': body(TARGET_BOX, 0.0 if index < 30 else 0.15)})
        return detections


class FakeCamera:
    def __init__(self, matrix=IDENTITY):
        self.matrix, self.calls = matrix, []

    def estimate(self, previous_image, previous_boxes, image, boxes):
        self.calls.append((previous_image.info['frame_index'], image.info['frame_index'],
                           len(previous_boxes), len(boxes)))
        return None if self.matrix is None else list(self.matrix)


class LargeMovementReaderTests(unittest.TestCase):
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

    def read(self, detector, camera, output='movement', uncertain=(), **options):
        from aba_demo.large_movement_reader import read_large_movement
        self.candidate.write_text(json.dumps(candidate(self.source_sha, uncertain=set(uncertain))),
                                  encoding='utf-8')
        return read_large_movement(self.video, self.candidate, self.root / output,
                                   detector=detector, motion_estimator=camera,
                                   frame_reader_factory=FakeReader, **options)

    def document(self, output='movement'):
        path = self.root / output / 'large_movement.pending.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def test_reading_writes_a_valid_bound_document_with_one_episode(self):
        from aba_demo.large_movement_schema import validate_large_movement_document

        detector, camera = FakeDetector(), FakeCamera()
        report = self.read(detector, camera, uncertain={50})
        document = validate_large_movement_document(self.document(), 6.1)
        self.assertEqual(document['source_sha256'], self.source_sha)
        self.assertEqual(document['tracking_candidate_sha256'],
                         hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        self.assertEqual([(e['kind'], e['start_time'], e['end_time'], e['detected_time'])
                          for e in document['events']], [('large_movement', 2.5, 3.0, 5.0)])
        self.assertTrue(all(e['clinician_confirmation'] == 'pending' for e in document['events']))
        uncertain = [s for s in document['samples'] if s['identity'] == 'uncertain']
        self.assertEqual([(s['time'], s['centre']) for s in uncertain], [(5.0, None)])
        self.assertNotIn(50, detector.calls)
        self.assertEqual(camera.calls[0], (0, 5, 2, 2))
        self.assertNotIn(50, [call[1] for call in camera.calls])
        self.assertNotIn(55, [call[1] for call in camera.calls])
        self.assertEqual(FakeReader.instances[0].requested,
                         sorted(FakeReader.instances[0].requested))
        self.assertTrue(FakeReader.instances[0].closed)
        self.assertEqual(report['event_counts'], {'large_movement': 1})
        self.assertEqual(report['state_counts'],
                         {'identity_uncertain': 1, 'measured': 9, 'segment_start': 2})
        encoded = (self.root / 'movement' / 'large_movement.pending.json').read_bytes()
        self.assertEqual(report['large_movement_candidate_sha256'],
                         hashlib.sha256(encoded).hexdigest())

    def test_another_persons_skeleton_is_never_used_for_the_child(self):
        self.read(FakeDetector(child_visible=False), FakeCamera())
        states = {s['state'] for s in self.document()['samples'] if s['identity'] == 'confirmed'}
        self.assertEqual(states, {'not_measurable'})
        self.assertEqual(self.document()['events'], [])

    def test_unreliable_camera_or_identity_gap_between_samples_measures_nothing_across(self):
        self.read(FakeDetector(), FakeCamera(None), output='no-camera')
        self.assertEqual({s['state'] for s in self.document('no-camera')['samples']},
                         {'segment_start'})
        self.read(FakeDetector(), FakeCamera([1.0, 0.0, 0.5, 0.0, 1.0, 0.0]), output='jump')
        self.assertEqual(self.document('jump')['events'], [])
        camera = FakeCamera()
        self.read(FakeDetector(), camera, output='gap', uncertain={27})
        document = self.document('gap')
        self.assertEqual(document['events'], [])
        self.assertEqual([s['state'] for s in document['samples'] if s['time'] == 3.0],
                         ['segment_start'])
        self.assertNotIn((25, 30, 2, 2), camera.calls)

    def test_refuses_wrong_video_repository_output_and_overwrite(self):
        from aba_demo.large_movement_reader import read_large_movement

        self.read(FakeDetector(), FakeCamera(), output='once')
        with self.assertRaisesRegex(ValueError, 'large_movement_candidate_exists'):
            self.read(FakeDetector(), FakeCamera(), output='once')
        with self.assertRaisesRegex(ValueError, 'output_inside_repository'):
            self.read(FakeDetector(), FakeCamera(),
                      output=ROOT / 'tests' / 'large-movement-must-not-exist')
        self.assertFalse((ROOT / 'tests' / 'large-movement-must-not-exist').exists())
        other = self.root / 'other.mp4'
        other.write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'video_does_not_match_tracking_candidate'):
            read_large_movement(other, self.candidate, self.root / 'x', detector=FakeDetector(),
                                motion_estimator=FakeCamera(), frame_reader_factory=FakeReader)


class BackgroundMotionTests(unittest.TestCase):
    def test_estimates_a_known_background_shift_in_frame_height_units(self):
        import numpy
        from PIL import Image
        from aba_demo.large_movement_reader import BackgroundMotionEstimator

        generator = numpy.random.default_rng(7)
        texture = (generator.random((60, 80)) * 255).astype('uint8')
        big = numpy.asarray(Image.fromarray(texture).resize((400, 300), Image.BILINEAR))
        previous = Image.fromarray(big[:, :360]).convert('RGB')
        shifted = Image.fromarray(big[:, 9:369]).convert('RGB')
        estimator = BackgroundMotionEstimator(min_inliers=12, working_height=300)
        matrix = estimator.estimate(previous, [[0.4, 0.4, 0.6, 0.6]], shifted,
                                    [[0.4, 0.4, 0.6, 0.6]])
        self.assertIsNotNone(matrix)
        self.assertAlmostEqual(matrix[2], -9 / 300, delta=0.005)
        self.assertAlmostEqual(matrix[5], 0.0, delta=0.005)
        flat = Image.new('RGB', (360, 300))
        self.assertIsNone(estimator.estimate(flat, [], flat, []))


class LargeMovementScriptTests(unittest.TestCase):
    def test_script_prints_counts_and_writes_one_evidence_sheet_per_event(self):
        import contextlib
        import importlib.util
        import io

        spec = importlib.util.spec_from_file_location(
            'run_large_movement_reader', ROOT / 'scripts' / 'run_large_movement_reader.py')
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
                                   motion_estimator_factory=lambda arguments: FakeCamera(),
                                   frame_reader_factory=FakeReader)
            text = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("EVENT_COUNTS {'large_movement': 1}", text)
            self.assertIn('NOT_MEASURABLE_SHARE 0.000', text)
            self.assertNotIn(source_sha, text)
            sheets = sorted((root / 'out' / 'evidence').glob('*.png'))
            self.assertEqual([sheet.name for sheet in sheets], ['lmv-000000.png'])


if __name__ == '__main__':
    unittest.main()
