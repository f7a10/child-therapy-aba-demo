"""Decode planned movement windows into target-grounded image windows.

Frames are re-decoded forward-only from the SHA-verified source with the same
numbering as ``VideoAnalyzer`` (frame N is the Nth successful read); detection
and tracking are never rerun. Each window uses one crop region for all of its
frames so whole-body displacement stays visible against the background. Only
the full scene carries the green target outline; the crop stays unannotated.
"""

import hashlib
import math

from .colab_workflow import _bounded_jpeg
from .context_schema import validate_context_window
from .movement_schema import CROP_MODES, MAX_WINDOW_FRAMES, MIN_WINDOW_FRAMES


CROP_MARGIN = 0.15


class SequentialFrameReader:
    """Forward-only RGB frame reader for one local video file."""

    def __init__(self, video_path):
        import cv2

        self._cv2 = cv2
        self._capture = cv2.VideoCapture(str(video_path))
        self._index = -1
        if not self._capture.isOpened():
            self._capture.release()
            raise ValueError('video_unreadable')

    def read(self, index):
        """Return decoded frame ``index`` as a PIL RGB image; indices must increase."""
        from PIL import Image

        if type(index) is not int or index <= self._index:
            raise ValueError('frames_must_be_requested_forward')
        frame = None
        while self._index < index:
            ok, frame = self._capture.read()
            if not ok:
                raise ValueError('video_ended_before_window_frames')
            self._index += 1
        return Image.fromarray(self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB))

    def close(self):
        self._capture.release()


def _valid_box(box):
    return (isinstance(box, list) and len(box) == 4
            and all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
                    for value in box)
            and box[0] < box[2] and box[1] < box[3])


def window_crop_box(boxes, margin=CROP_MARGIN):
    """Union of the window's target boxes, expanded by ``margin`` and clamped."""
    left, top = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, bottom = max(box[2] for box in boxes), max(box[3] for box in boxes)
    pad_x, pad_y = (right - left) * margin, (bottom - top) * margin
    return [max(0.0, left - pad_x), max(0.0, top - pad_y),
            min(1.0, right + pad_x), min(1.0, bottom + pad_y)]


def _pixels(box, width, height):
    return (math.floor(box[0] * width), math.floor(box[1] * height),
            math.ceil(box[2] * width), math.ceil(box[3] * height))


def build_movement_window(window_frames, images, *, crop_mode='window_stable'):
    """Build the exact provider window for planned frames and their decoded images.

    ``window_stable_others_marked`` also outlines every other tracked person in red,
    in the scene and in the crop, so their hands and toys are not read as the child's.
    Returns ``{'frames', 'crop_box', 'image_sha256'}``; hashes follow send order
    (scene, crop) per frame. Images stay in memory.
    """
    from PIL import ImageDraw

    marked = crop_mode == 'window_stable_others_marked'
    if (crop_mode not in CROP_MODES
            or not isinstance(window_frames, list) or not isinstance(images, list)
            or not MIN_WINDOW_FRAMES <= len(window_frames) <= MAX_WINDOW_FRAMES
            or len(images) != len(window_frames)
            or any(not isinstance(frame, dict) or not _valid_box(frame.get('target_box'))
                   for frame in window_frames)
            or marked and any(not isinstance(frame.get('other_boxes'), list)
                              or not all(map(_valid_box, frame['other_boxes']))
                              for frame in window_frames)
            or len({image.size for image in images}) != 1):
        raise ValueError('invalid_movement_window')
    width, height = images[0].size
    crop_box = window_crop_box([frame['target_box'] for frame in window_frames])
    crop_pixels = _pixels(crop_box, width, height)
    sent, hashes = [], []
    line = max(3, min(width, height) // 60)
    for frame, image in zip(window_frames, images):
        scene = image.convert('RGB')
        if marked:
            others = scene.copy()
            for box in frame['other_boxes']:
                o_left, o_top, o_right, o_bottom = _pixels(box, width, height)
                ImageDraw.Draw(others).rectangle(
                    (o_left, o_top, min(o_right, width - 1), min(o_bottom, height - 1)),
                    outline=(255, 0, 0), width=line)
            scene = others
        left, top, right, bottom = _pixels(frame['target_box'], width, height)
        outlined = scene.copy()
        ImageDraw.Draw(outlined).rectangle(
            (left, top, min(right, width - 1), min(bottom, height - 1)),
            outline=(0, 255, 0), width=line)
        scene_jpeg = _bounded_jpeg(outlined)
        crop_jpeg = _bounded_jpeg(scene.crop(crop_pixels))
        sent.append({'time': frame.get('time'), 'identity': 'confirmed',
                     'scene_jpeg': scene_jpeg, 'target_crop_jpeg': crop_jpeg,
                     'target_box': list(frame['target_box'])})
        hashes.extend(hashlib.sha256(value).hexdigest() for value in (scene_jpeg, crop_jpeg))
    try:
        validate_context_window(sent)
    except ValueError:
        raise ValueError('invalid_movement_window') from None
    return {'frames': sent, 'crop_box': crop_box, 'image_sha256': hashes}
