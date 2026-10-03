"""Local large-movement reading of the selected child over a recorded session.

Consumes a finished, quality-passed tracking candidate and its exact source
video. For every confirmed 5 Hz sample it runs a local pose detector on that
frame and keeps only the detection that overlaps the tracked child box (another
person's skeleton is never substituted), takes the child's hip midpoint and
torso length, and estimates the camera step since the previous measured sample
from background features outside every tracked person box. A camera step is
only estimated across frames that the dense causal audit keeps on one confirmed
target binding. A step where the camera itself moves more than
``max_camera_shift`` is discarded (parallax cannot be compensated in 2D), so the
next sample starts a new segment. Only horizontal displacement counts as a large
movement. Writes a pending, source- and tracking-bound document. Nothing leaves
the machine.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path

from .colab_workflow import _write_bytes
from .export import file_sha256
from .large_movement_features import (
    DISPLACEMENT_THRESHOLD, KEYPOINT_CONFIDENCE, MAX_CAMERA_SCALE_CHANGE, MAX_CAMERA_SHIFT,
    MAX_GAP_SECONDS, MERGE_GAP_SECONDS, WINDOW_SECONDS, body_centre, large_movement_events,
    sample_states, valid_camera)
from .large_movement_schema import encode_large_movement_document
from .movement_frames import SequentialFrameReader
from .movement_windows import decoded_seconds, load_tracking_candidate
from .posture_reader import MATCH_IOU_MIN, _child_keypoints


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MIN_CAMERA_INLIERS = 12


class BackgroundMotionEstimator:
    """Partial-affine camera step from background features outside person boxes.

    Returns ``[a, b, tx, c, d, ty]`` mapping previous-frame points to the current
    frame in frame-height units, or None when too few background points agree.
    """

    def __init__(self, *, min_inliers=MIN_CAMERA_INLIERS, working_height=360, box_margin=0.02):
        self.min_inliers = min_inliers
        self.working_height = working_height
        self.box_margin = box_margin

    def _gray(self, image):
        import cv2
        import numpy

        rgb = numpy.asarray(image.convert('RGB'))
        height, width = rgb.shape[:2]
        size = (max(1, round(width * self.working_height / height)), self.working_height)
        return cv2.cvtColor(cv2.resize(rgb, size), cv2.COLOR_RGB2GRAY)

    def _mask(self, gray, boxes):
        import numpy

        height, width = gray.shape
        mask = numpy.full(gray.shape, 255, numpy.uint8)
        for x1, y1, x2, y2 in boxes:
            left = max(0, int((x1 - self.box_margin) * width))
            top = max(0, int((y1 - self.box_margin) * height))
            right = min(width, int((x2 + self.box_margin) * width) + 1)
            bottom = min(height, int((y2 + self.box_margin) * height) + 1)
            mask[top:bottom, left:right] = 0
        return mask

    def estimate(self, previous_image, previous_boxes, image, boxes):
        import cv2

        previous, current = self._gray(previous_image), self._gray(image)
        if previous.shape != current.shape:
            return None
        points = cv2.goodFeaturesToTrack(previous, 300, 0.01, 8,
                                         mask=self._mask(previous, previous_boxes))
        if points is None or len(points) < self.min_inliers:
            return None
        moved, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
        if moved is None or status is None:
            return None
        good = status.ravel() == 1
        if good.sum() < self.min_inliers:
            return None
        matrix, inliers = cv2.estimateAffinePartial2D(points[good], moved[good],
                                                      ransacReprojThreshold=2.0)
        if matrix is None or inliers is None or int(inliers.sum()) < self.min_inliers:
            return None
        height = self.working_height
        return [float(matrix[0, 0]), float(matrix[0, 1]), float(matrix[0, 2] / height),
                float(matrix[1, 0]), float(matrix[1, 1]), float(matrix[1, 2] / height)]


def _continuity(audit):
    """Prefix counts of identity breaks: frames k..i are one binding iff counts match."""
    breaks, counts = 0, []
    for index, row in enumerate(audit):
        previous = audit[index - 1] if index else None
        if (row['identity'] != 'confirmed' or previous is not None
                and (previous['identity'] != 'confirmed'
                     or previous['target_id'] != row['target_id'])):
            breaks += 1
        counts.append(breaks)
    return counts


def read_large_movement(video_path, candidate_path, output_dir, *, detector,
                        motion_estimator=None, weights_name='yolo11s-pose.pt',
                        keypoint_confidence=KEYPOINT_CONFIDENCE, match_iou_min=MATCH_IOU_MIN,
                        displacement_threshold=DISPLACEMENT_THRESHOLD,
                        window_seconds=WINDOW_SECONDS, merge_gap_seconds=MERGE_GAP_SECONDS,
                        max_gap_seconds=MAX_GAP_SECONDS, max_camera_shift=MAX_CAMERA_SHIFT,
                        max_camera_scale_change=MAX_CAMERA_SCALE_CHANGE,
                        min_camera_inliers=MIN_CAMERA_INLIERS,
                        frame_reader_factory=SequentialFrameReader, progress=None,
                        repository_root=REPOSITORY_ROOT):
    """Write ``large_movement.pending.json`` and ``large_movement-report.json``; return counts."""
    video_path, output_dir = Path(video_path), Path(output_dir).resolve()
    if output_dir.is_relative_to(Path(repository_root).resolve()):
        raise ValueError('output_inside_repository')
    pending = output_dir / 'large_movement.pending.json'
    report_path = output_dir / 'large_movement-report.json'
    if pending.exists() or report_path.exists():
        raise ValueError('large_movement_candidate_exists')
    data, tracking_sha = load_tracking_candidate(candidate_path)
    source = data['source']
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_does_not_match_tracking_candidate')
    if motion_estimator is None:
        motion_estimator = BackgroundMotionEstimator(min_inliers=min_camera_inliers)
    config = {'weights': weights_name, 'keypoint_confidence': keypoint_confidence,
              'match_iou_min': match_iou_min, 'displacement_threshold': displacement_threshold,
              'window_seconds': window_seconds, 'merge_gap_seconds': merge_gap_seconds,
              'max_gap_seconds': max_gap_seconds, 'max_camera_shift': max_camera_shift,
              'max_camera_scale_change': max_camera_scale_change,
              'min_camera_inliers': min_camera_inliers}
    audit = data['provenance']['causal_audit']
    breaks = _continuity(audit)
    frame_of_time = {row['time']: row['frame_index'] for row in audit}
    rows = sorted(data['observations'], key=lambda row: row['time'])
    samples, anchor = [], None
    reader = frame_reader_factory(video_path)
    try:
        for number, row in enumerate(rows):
            index = frame_of_time[row['time']]
            if samples and index <= samples[-1]['frame_index']:
                raise ValueError('invalid_tracking_candidate')
            if row['identity'] != 'confirmed':
                samples.append({'time': row['time'], 'frame_index': index,
                                'identity': 'uncertain', 'state': None, 'centre': None,
                                'torso': None, 'camera': None})
                anchor = None
                continue
            image = reader.read(index)
            boxes = [list(box['xyxy']) for box in row['boxes']]
            target = [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']][0]
            points = _child_keypoints(detector.detect(image), target, match_iou_min)
            width, height = image.size
            measured = body_centre(points, aspect=width / height,
                                   keypoint_confidence=keypoint_confidence)
            camera = None
            if measured is not None:
                if (anchor is not None and breaks[index] == breaks[anchor['frame_index']]
                        and row['time'] - anchor['time'] <= max_gap_seconds):
                    camera = motion_estimator.estimate(anchor['image'], anchor['boxes'],
                                                       image, boxes)
                    if not valid_camera(camera, max_shift=max_camera_shift,
                                        max_scale_change=max_camera_scale_change):
                        camera = None
                anchor = {'time': row['time'], 'frame_index': index, 'image': image,
                          'boxes': boxes}
            samples.append({'time': row['time'], 'frame_index': index, 'identity': 'confirmed',
                            'state': None,
                            'centre': None if measured is None else measured['centre'],
                            'torso': None if measured is None else measured['torso'],
                            'camera': camera})
            if progress and (number + 1) % 100 == 0:
                progress(number + 1, len(rows))
    finally:
        reader.close()
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_changed_during_reading')
    for sample, state in zip(samples, sample_states(samples, max_gap_seconds=max_gap_seconds)):
        sample['state'] = state
    events = [{'event_id': f'lmv-{number:06d}', **event, 'clinician_confirmation': 'pending'}
              for number, event in enumerate(large_movement_events(
                  samples, displacement_threshold=displacement_threshold,
                  window_seconds=window_seconds, merge_gap_seconds=merge_gap_seconds,
                  max_gap_seconds=max_gap_seconds))]
    document = {'schema_version': 1, 'kind': 'large_movement_reading',
                'source_sha256': source['sha256'], 'tracking_candidate_sha256': tracking_sha,
                'config': config, 'decoded_seconds': decoded_seconds(data),
                'samples': samples, 'events': events}
    encoded = encode_large_movement_document(document, source['duration'])
    report = {
        'large_movement_candidate_sha256': hashlib.sha256(encoded).hexdigest(),
        'tracking_candidate_sha256': tracking_sha, 'source_sha256': source['sha256'],
        'state_counts': dict(sorted(Counter(sample['state'] or 'identity_uncertain'
                                            for sample in samples).items())),
        'event_counts': dict(sorted(Counter(event['kind'] for event in events).items())),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        _write_bytes(pending, encoded)
        _write_bytes(report_path, json.dumps(report, sort_keys=True, indent=1).encode('utf-8'))
    except BaseException:
        pending.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise
    return report
