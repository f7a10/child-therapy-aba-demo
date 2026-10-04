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
from pathlib import Path

from .channel_pass import check_output_dir, load_bound_candidate, run_pass
from .large_movement_features import (
    DISPLACEMENT_THRESHOLD, KEYPOINT_CONFIDENCE, MAX_CAMERA_SCALE_CHANGE, MAX_CAMERA_SHIFT,
    MAX_GAP_SECONDS, MERGE_GAP_SECONDS, WINDOW_SECONDS, body_centre, large_movement_events,
    sample_states, valid_camera)
from .large_movement_schema import encode_large_movement_document
from .movement_frames import SequentialFrameReader
from .movement_windows import decoded_seconds
from .posture_reader import MATCH_IOU_MIN, _child_keypoints, write_job_output


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


class LargeMovementJob:
    """Large movement over the samples of one pass (see ``channel_pass``)."""
    PENDING, REPORT = 'large_movement.pending.json', 'large_movement-report.json'

    def __init__(self, data, tracking_sha, output_dir, *, motion_estimator=None,
                 weights_name='yolo11s-pose.pt', keypoint_confidence=KEYPOINT_CONFIDENCE,
                 match_iou_min=MATCH_IOU_MIN, displacement_threshold=DISPLACEMENT_THRESHOLD,
                 window_seconds=WINDOW_SECONDS, merge_gap_seconds=MERGE_GAP_SECONDS,
                 max_gap_seconds=MAX_GAP_SECONDS, max_camera_shift=MAX_CAMERA_SHIFT,
                 max_camera_scale_change=MAX_CAMERA_SCALE_CHANGE,
                 min_camera_inliers=MIN_CAMERA_INLIERS):
        self.data, self.tracking_sha, self.output_dir = data, tracking_sha, Path(output_dir)
        self.motion_estimator = (motion_estimator if motion_estimator is not None
                                 else BackgroundMotionEstimator(min_inliers=min_camera_inliers))
        self.config = {'weights': weights_name, 'keypoint_confidence': keypoint_confidence,
                       'match_iou_min': match_iou_min,
                       'displacement_threshold': displacement_threshold,
                       'window_seconds': window_seconds, 'merge_gap_seconds': merge_gap_seconds,
                       'max_gap_seconds': max_gap_seconds, 'max_camera_shift': max_camera_shift,
                       'max_camera_scale_change': max_camera_scale_change,
                       'min_camera_inliers': min_camera_inliers}
        self.breaks = _continuity(data['provenance']['causal_audit'])
        self.samples, self.anchor = [], None

    def step(self, number, row, index, frame, context):
        config = self.config
        if row['identity'] != 'confirmed':
            self.samples.append({'time': row['time'], 'frame_index': index,
                                 'identity': 'uncertain', 'state': None, 'centre': None,
                                 'torso': None, 'camera': None})
            self.anchor = None
            return
        image = frame.image
        boxes = [list(box['xyxy']) for box in row['boxes']]
        target = [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']][0]
        points = _child_keypoints(frame.detections(), target, config['match_iou_min'])
        width, height = image.size
        measured = body_centre(points, aspect=width / height,
                               keypoint_confidence=config['keypoint_confidence'])
        camera = None
        anchor = self.anchor
        if measured is not None:
            if (anchor is not None and self.breaks[index] == self.breaks[anchor['frame_index']]
                    and row['time'] - anchor['time'] <= config['max_gap_seconds']):
                camera = context.estimate(self.motion_estimator, anchor['frame'], anchor['boxes'],
                                          frame, boxes)
                if not valid_camera(camera, max_shift=config['max_camera_shift'],
                                    max_scale_change=config['max_camera_scale_change']):
                    camera = None
            self.anchor = {'time': row['time'], 'frame_index': index, 'frame': frame,
                           'boxes': boxes}
        self.samples.append({'time': row['time'], 'frame_index': index, 'identity': 'confirmed',
                             'state': None,
                             'centre': None if measured is None else measured['centre'],
                             'torso': None if measured is None else measured['torso'],
                             'camera': camera})

    def finish(self):
        data, samples, config = self.data, self.samples, self.config
        source = data['source']
        self.anchor = None
        for sample, state in zip(samples, sample_states(
                samples, max_gap_seconds=config['max_gap_seconds'])):
            sample['state'] = state
        events = [{'event_id': f'lmv-{number:06d}', **event, 'clinician_confirmation': 'pending'}
                  for number, event in enumerate(large_movement_events(
                      samples, displacement_threshold=config['displacement_threshold'],
                      window_seconds=config['window_seconds'],
                      merge_gap_seconds=config['merge_gap_seconds'],
                      max_gap_seconds=config['max_gap_seconds']))]
        document = {'schema_version': 1, 'kind': 'large_movement_reading',
                    'source_sha256': source['sha256'],
                    'tracking_candidate_sha256': self.tracking_sha, 'config': config,
                    'decoded_seconds': decoded_seconds(data), 'samples': samples,
                    'events': events}
        encoded = encode_large_movement_document(document, source['duration'])
        report = {
            'large_movement_candidate_sha256': hashlib.sha256(encoded).hexdigest(),
            'tracking_candidate_sha256': self.tracking_sha, 'source_sha256': source['sha256'],
            'state_counts': dict(sorted(Counter(sample['state'] or 'identity_uncertain'
                                                for sample in samples).items())),
            'event_counts': dict(sorted(Counter(event['kind'] for event in events).items())),
        }
        write_job_output(self.output_dir, self.PENDING, encoded, self.REPORT, report)
        return report


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
    output_dir = check_output_dir(output_dir, (LargeMovementJob.PENDING, LargeMovementJob.REPORT),
                                  repository_root, 'large_movement_candidate_exists')
    data, tracking_sha = load_bound_candidate(video_path, candidate_path)
    job = LargeMovementJob(data, tracking_sha, output_dir, motion_estimator=motion_estimator,
                           weights_name=weights_name, keypoint_confidence=keypoint_confidence,
                           match_iou_min=match_iou_min,
                           displacement_threshold=displacement_threshold,
                           window_seconds=window_seconds, merge_gap_seconds=merge_gap_seconds,
                           max_gap_seconds=max_gap_seconds, max_camera_shift=max_camera_shift,
                           max_camera_scale_change=max_camera_scale_change,
                           min_camera_inliers=min_camera_inliers)
    return run_pass(Path(video_path), data, [job], detector=detector,
                    frame_reader_factory=frame_reader_factory, progress=progress)[0]
