"""One pass for all local channels: same bytes as separate readers, less work, isolated failures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from movement_fixtures import candidate
from test_orientation_reader import REGION, FakeDetector, FakeMotion, FakeReader

FILES = {'posture': 'posture.pending.json', 'movement': 'large_movement.pending.json',
         'orientation': 'orientation.pending.json'}


class LocalChannelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / 'authorized.mp4'
        self.video.write_bytes(b'synthetic-source-not-video')
        source = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.candidate = self.root / 'observations.pending.json'
        self.candidate.write_text(json.dumps(candidate(source, uncertain={20, 50})),
                                  encoding='utf-8')
        FakeReader.instances = []

    def tearDown(self):
        self.temp.cleanup()

    def separate(self):
        from aba_demo.large_movement_reader import read_large_movement
        from aba_demo.orientation_reader import read_orientation
        from aba_demo.posture_reader import read_posture

        options = dict(frame_reader_factory=FakeReader)
        read_posture(self.video, self.candidate, self.root / 'alone' / 'posture',
                     detector=FakeDetector(), **options)
        read_large_movement(self.video, self.candidate, self.root / 'alone' / 'movement',
                            detector=FakeDetector(), motion_estimator=FakeMotion(moving={35}),
                            **options)
        read_orientation(self.video, self.candidate, self.root / 'alone' / 'orientation',
                         task_region=REGION, detector=FakeDetector(),
                         motion_estimator=FakeMotion(moving={35}), **options)

    def combined(self, detector, motion, **options):
        from aba_demo.local_channels import read_local_channels

        outputs = {name: self.root / 'together' / name for name in FILES}
        return read_local_channels(self.video, self.candidate, outputs, detector=detector,
                                   task_region=REGION, motion_estimator=motion,
                                   frame_reader_factory=FakeReader, **options)

    def test_one_pass_writes_the_same_documents_with_less_work(self):
        self.separate()
        separate_readers = len(FakeReader.instances)
        FakeReader.instances = []
        detector, motion = FakeDetector(), FakeMotion(moving={35})
        reports, errors = self.combined(detector, motion)
        self.assertEqual((sorted(reports), errors), (sorted(FILES), {}))
        for name, filename in FILES.items():
            self.assertEqual((self.root / 'together' / name / filename).read_bytes(),
                             (self.root / 'alone' / name / filename).read_bytes(), name)
        self.assertEqual((separate_readers, len(FakeReader.instances)), (3, 1))
        requested = FakeReader.instances[0].requested
        self.assertEqual(requested, sorted(set(requested)))  # each frame decoded once, in order
        self.assertEqual(len(detector.calls), len(set(detector.calls)))  # pose once per frame
        self.assertNotIn(20, detector.calls)
        steps = [(previous, index) for previous, index, _ in motion.calls]
        self.assertEqual(len(steps), len(set(steps)))  # each camera step computed once

    def test_a_failing_channel_does_not_stop_the_others(self):
        from aba_demo.local_channels import JOBS

        class Broken(JOBS['posture']):
            def step(self, *args):
                raise ValueError('posture_broke')

        with mock.patch.dict(JOBS, {'posture': Broken}):
            reports, errors = self.combined(FakeDetector(), FakeMotion())
        self.assertEqual(sorted(reports), ['movement', 'orientation'])
        self.assertEqual({name: str(error) for name, error in errors.items()},
                         {'posture': 'posture_broke'})
        self.assertFalse((self.root / 'together' / 'posture' / FILES['posture']).exists())

    def test_inputs_are_checked_before_any_frame_is_read(self):
        from aba_demo.local_channels import read_local_channels

        with self.assertRaisesRegex(ValueError, 'invalid_task_region'):
            read_local_channels(self.video, self.candidate,
                                {'orientation': self.root / 'x'}, detector=FakeDetector(),
                                task_region=None, frame_reader_factory=FakeReader)
        with self.assertRaisesRegex(ValueError, 'invalid_channels'):
            read_local_channels(self.video, self.candidate, {'context': self.root / 'x'},
                                detector=FakeDetector(), frame_reader_factory=FakeReader)
        (self.root / 'together' / 'movement').mkdir(parents=True)
        (self.root / 'together' / 'movement' / FILES['movement']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'large_movement_candidate_exists'):
            self.combined(FakeDetector(), FakeMotion())
        self.assertEqual(FakeReader.instances, [])


if __name__ == '__main__':
    unittest.main()
