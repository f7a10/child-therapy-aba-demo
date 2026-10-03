"""Forward-only decoding and target-grounded movement window images."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest


def frames():
    return [{'frame_index': 0, 'time': 0.0, 'target_box': [0.1, 0.2, 0.3, 0.8]},
            {'frame_index': 5, 'time': 0.5, 'target_box': [0.2, 0.2, 0.4, 0.9]}]


def images(size=(200, 100)):
    from PIL import Image
    return [Image.new('RGB', size, (200, 60, 60)), Image.new('RGB', size, (60, 60, 200))]


def decode(jpeg):
    from PIL import Image
    return Image.open(io.BytesIO(jpeg)).convert('RGB')


def green_pixels(image):
    data = image.tobytes()
    return sum(1 for offset in range(0, len(data), 3)
               if data[offset + 1] > 180 and data[offset] < 90 and data[offset + 2] < 90)


class MovementWindowImageTests(unittest.TestCase):
    def test_window_uses_one_stable_crop_and_outlines_only_the_scene(self):
        from aba_demo.context_schema import validate_context_window
        from aba_demo.movement_frames import build_movement_window

        window = build_movement_window(frames(), images())
        sent = window['frames']
        self.assertEqual(validate_context_window(sent), [0.0, 0.5])
        self.assertEqual([frame['target_box'] for frame in sent],
                         [f['target_box'] for f in frames()])
        crop = window['crop_box']
        for actual, expected in zip(crop, [0.055, 0.095, 0.445, 1.0]):
            self.assertAlmostEqual(actual, expected)
        crops = [decode(frame['target_crop_jpeg']) for frame in sent]
        self.assertEqual(crops[0].size, crops[1].size)
        self.assertLessEqual(abs(crops[0].width - 78), 1)
        self.assertLessEqual(abs(crops[0].height - 91), 1)
        for frame, crop_image in zip(sent, crops):
            self.assertGreater(green_pixels(decode(frame['scene_jpeg'])), 50)
            self.assertEqual(green_pixels(crop_image), 0)
        self.assertEqual(window['image_sha256'], [
            hashlib.sha256(frame[key]).hexdigest()
            for frame in sent for key in ('scene_jpeg', 'target_crop_jpeg')])
        self.assertEqual(build_movement_window(frames(), images())['image_sha256'],
                         window['image_sha256'])

    def test_marked_mode_outlines_other_people_in_red_in_scene_and_crop(self):
        from aba_demo.movement_frames import build_movement_window

        def red_pixels(image):
            data = image.tobytes()
            return sum(1 for offset in range(0, len(data), 3)
                       if data[offset] > 180 and data[offset + 1] < 90 and data[offset + 2] < 90)

        marked_frames = [{**frame, 'other_boxes': [[0.35, 0.1, 0.9, 0.95]]} for frame in frames()]
        plain_images = [image.convert('L').convert('RGB') for image in images((640, 360))]
        marked = build_movement_window(marked_frames, plain_images,
                                       crop_mode='window_stable_others_marked')
        plain = build_movement_window(marked_frames, plain_images)
        for frame in marked['frames']:
            self.assertGreater(red_pixels(decode(frame['scene_jpeg'])), 50)
            self.assertGreater(red_pixels(decode(frame['target_crop_jpeg'])), 20)
            self.assertEqual(green_pixels(decode(frame['target_crop_jpeg'])), 0)
        for frame in plain['frames']:
            self.assertEqual(red_pixels(decode(frame['scene_jpeg'])), 0)
        self.assertNotEqual(marked['image_sha256'], plain['image_sha256'])
        with self.assertRaisesRegex(ValueError, 'invalid_movement_window'):
            build_movement_window(frames(), plain_images, crop_mode='window_stable_others_marked')
        with self.assertRaisesRegex(ValueError, 'invalid_movement_window'):
            build_movement_window(marked_frames, plain_images, crop_mode='other')

    def test_window_rejects_mismatched_or_single_frame_inputs(self):
        from aba_demo.movement_frames import build_movement_window

        mixed = images()
        mixed[1] = images((100, 100))[1]
        cases = [(frames(), images()[:1]), (frames()[:1], images()[:1]), (frames(), mixed),
                 ([{**frames()[0], 'target_box': [0.5, 0.2, 0.3, 0.8]}, frames()[1]], images()),
                 ([frames()[1], frames()[0]], images())]
        for window_frames, window_images in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_movement_window'):
                build_movement_window(window_frames, window_images)


@unittest.skipUnless(importlib.util.find_spec('cv2') and importlib.util.find_spec('numpy'),
                     'OpenCV not installed')
class SequentialFrameReaderTests(unittest.TestCase):
    def test_reader_matches_tracker_numbering_and_is_forward_only(self):
        import cv2
        import numpy
        from aba_demo.movement_frames import SequentialFrameReader

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'numbered.avi'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
            self.assertTrue(writer.isOpened())
            for index in range(6):
                writer.write(numpy.full((48, 64, 3), index * 40, dtype=numpy.uint8))
            writer.release()
            reader = SequentialFrameReader(path)
            try:
                levels = []
                for index in (0, 3, 5):
                    image = reader.read(index)
                    self.assertEqual(image.size, (64, 48))
                    levels.append(round(sum(image.convert('L').tobytes()) / (64 * 48) / 40))
                self.assertEqual(levels, [0, 3, 5])
                with self.assertRaisesRegex(ValueError, 'frames_must_be_requested_forward'):
                    reader.read(5)
                with self.assertRaisesRegex(ValueError, 'video_ended_before_window_frames'):
                    reader.read(9)
            finally:
                reader.close()
            with self.assertRaisesRegex(ValueError, 'video_unreadable'):
                SequentialFrameReader(Path(directory) / 'missing.avi')


if __name__ == '__main__':
    unittest.main()
