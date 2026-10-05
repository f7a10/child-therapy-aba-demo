"""Local orientation reading of the selected child over a recorded session.

Consumes a finished, quality-passed tracking candidate, its exact source video
and the therapist-drawn task region (normalized ``[x1, y1, x2, y2]``, fixed
camera assumed). For every confirmed 5 Hz sample it runs a local pose detector
on that frame and keeps only the skeleton matching the tracked child box (IoU);
another person's skeleton is never substituted. The same skeleton's posture
leg ratio (stable seated posture, causal) and the background camera step since
the previous sample gate the state. Writes a pending, source- and
tracking-bound orientation document. Nothing leaves the machine.
"""

from collections import Counter
import hashlib
from pathlib import Path

from .channel_pass import check_output_dir, load_bound_candidate, run_pass
from .movement_frames import SequentialFrameReader
from .movement_windows import decoded_seconds
from .orientation_features import (
    AREA_AT_MIN, AREA_AWAY_MAX, AWAY_MIN_DEGREES, KEYPOINT_CONFIDENCE, MAX_CAMERA_SHIFT,
    MAX_GAP_SECONDS, MIN_FACING_LENGTH, MIN_STABLE_SAMPLES, POSTURE_MAX_GAP_SECONDS,
    POSTURE_MIN_STABLE_SAMPLES, TOWARD_MAX_DEGREES, area_overlap, area_states, camera_shift,
    facing_measure, orientation_events_v2, orientation_states, valid_task_region)
from .orientation_schema import encode_orientation_document
from .posture_features import SITTING_MAX_RATIO, STANDING_MIN_RATIO, leg_ratio
from .posture_reader import (MATCH_IOU_MIN, YoloPoseDetector, _child_keypoints,  # noqa: F401
                            write_job_output)


def _default_motion_estimator():
    from .large_movement_reader import BackgroundMotionEstimator

    return BackgroundMotionEstimator()


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class OrientationJob:
    """Facing the task region over the samples of one pass (see ``channel_pass``)."""
    PENDING, REPORT = 'orientation.pending.json', 'orientation-report.json'

    def __init__(self, data, tracking_sha, output_dir, *, task_region, motion_estimator=None,
                 weights_name='yolo11s-pose.pt', keypoint_confidence=KEYPOINT_CONFIDENCE,
                 toward_max_degrees=TOWARD_MAX_DEGREES, away_min_degrees=AWAY_MIN_DEGREES,
                 min_facing_length=MIN_FACING_LENGTH, min_stable_samples=MIN_STABLE_SAMPLES,
                 max_gap_seconds=MAX_GAP_SECONDS, match_iou_min=MATCH_IOU_MIN,
                 standing_min_ratio=STANDING_MIN_RATIO, sitting_max_ratio=SITTING_MAX_RATIO,
                 max_camera_shift=MAX_CAMERA_SHIFT,
                 posture_min_stable_samples=POSTURE_MIN_STABLE_SAMPLES,
                 posture_max_gap_seconds=POSTURE_MAX_GAP_SECONDS, area_at_min=AREA_AT_MIN,
                 area_away_max=AREA_AWAY_MAX):
        if not valid_task_region(task_region):
            raise ValueError('invalid_task_region')
        task_region = [float(value) for value in task_region]
        self.data, self.tracking_sha, self.output_dir = data, tracking_sha, Path(output_dir)
        self.motion_estimator = (motion_estimator if motion_estimator is not None
                                 else _default_motion_estimator())
        self.config = {'weights': weights_name, 'keypoint_confidence': keypoint_confidence,
                       'task_region': task_region, 'toward_max_degrees': toward_max_degrees,
                       'away_min_degrees': away_min_degrees,
                       'min_facing_length': min_facing_length,
                       'min_stable_samples': min_stable_samples,
                       'max_gap_seconds': max_gap_seconds, 'match_iou_min': match_iou_min,
                       'standing_min_ratio': standing_min_ratio,
                       'sitting_max_ratio': sitting_max_ratio,
                       'max_camera_shift': max_camera_shift,
                       'posture_min_stable_samples': posture_min_stable_samples,
                       'posture_max_gap_seconds': posture_max_gap_seconds,
                       'area_at_min': area_at_min, 'area_away_max': area_away_max}
        self.samples, self.previous = [], None

    def step(self, number, row, index, frame, context):
        config = self.config
        image = frame.image  # every sample is decoded in its own turn: the reader only goes forward
        boxes = [box['xyxy'] for box in row['boxes']]
        shift = (None if self.previous is None
                 else camera_shift(context.estimate(self.motion_estimator, self.previous[0],
                                                    self.previous[1], frame, boxes)))
        self.previous = (frame, boxes)
        if row['identity'] != 'confirmed':
            self.samples.append({'time': row['time'], 'frame_index': index,
                                 'identity': 'uncertain', 'state': None,
                                 'facing_angle': None, 'facing_length': None,
                                 'leg_ratio': None, 'camera_shift': None,
                                 'area_overlap': None, 'area_state': None})
            return
        target = [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']][0]
        points = _child_keypoints(frame.detections(), target, config['match_iou_min'])
        width, height = image.size
        angle, length = facing_measure(points, config['task_region'], aspect=width / height,
                                       keypoint_confidence=config['keypoint_confidence'])
        ratio = leg_ratio(points, keypoint_confidence=config['keypoint_confidence'])
        self.samples.append({'time': row['time'], 'frame_index': index, 'identity': 'confirmed',
                             'state': None, 'facing_angle': angle, 'facing_length': length,
                             'leg_ratio': ratio, 'camera_shift': shift,
                             'area_overlap': area_overlap(target, config['task_region']),
                             'area_state': None})

    def finish(self):
        data, samples, config = self.data, self.samples, self.config
        source = data['source']
        self.previous = None
        for sample, state, area in zip(samples, orientation_states(samples, config),
                                       area_states(samples, config)):
            sample['state'], sample['area_state'] = state, area
        events = [{'event_id': f'ori-{number:06d}', **event, 'clinician_confirmation': 'pending'}
                  for number, event in enumerate(orientation_events_v2(
                      samples, min_stable_samples=config['min_stable_samples'],
                      max_gap_seconds=config['max_gap_seconds']))]
        document = {'schema_version': 2, 'kind': 'orientation_reading',
                    'source_sha256': source['sha256'],
                    'tracking_candidate_sha256': self.tracking_sha, 'config': config,
                    'decoded_seconds': decoded_seconds(data), 'samples': samples,
                    'events': events}
        encoded = encode_orientation_document(document, source['duration'])
        report = {
            'orientation_candidate_sha256': hashlib.sha256(encoded).hexdigest(),
            'tracking_candidate_sha256': self.tracking_sha, 'source_sha256': source['sha256'],
            'state_counts': dict(sorted(Counter(sample['state'] or 'identity_uncertain'
                                                for sample in samples).items())),
            'area_counts': dict(sorted(Counter(sample['area_state'] or 'identity_uncertain'
                                               for sample in samples).items())),
            'event_counts': dict(sorted(Counter(event['kind'] for event in events).items())),
        }
        write_job_output(self.output_dir, self.PENDING, encoded, self.REPORT, report)
        return report


def read_orientation(video_path, candidate_path, output_dir, *, task_region, detector,
                     weights_name='yolo11s-pose.pt', keypoint_confidence=KEYPOINT_CONFIDENCE,
                     toward_max_degrees=TOWARD_MAX_DEGREES, away_min_degrees=AWAY_MIN_DEGREES,
                     min_facing_length=MIN_FACING_LENGTH, min_stable_samples=MIN_STABLE_SAMPLES,
                     max_gap_seconds=MAX_GAP_SECONDS, match_iou_min=MATCH_IOU_MIN,
                     standing_min_ratio=STANDING_MIN_RATIO, sitting_max_ratio=SITTING_MAX_RATIO,
                     max_camera_shift=MAX_CAMERA_SHIFT,
                     posture_min_stable_samples=POSTURE_MIN_STABLE_SAMPLES,
                     posture_max_gap_seconds=POSTURE_MAX_GAP_SECONDS, motion_estimator=None,
                     frame_reader_factory=SequentialFrameReader, progress=None,
                     repository_root=REPOSITORY_ROOT):
    """Write ``orientation.pending.json`` and ``orientation-report.json``; return counts only.

    ``motion_estimator.estimate(previous_image, previous_boxes, image, boxes)``
    returns the background camera step between consecutive 5 Hz sample frames
    (person boxes masked), or None when unreliable.
    """
    if not valid_task_region(task_region):
        raise ValueError('invalid_task_region')
    output_dir = check_output_dir(output_dir, (OrientationJob.PENDING, OrientationJob.REPORT),
                                  repository_root, 'orientation_candidate_exists')
    data, tracking_sha = load_bound_candidate(video_path, candidate_path)
    job = OrientationJob(data, tracking_sha, output_dir, task_region=task_region,
                         motion_estimator=motion_estimator, weights_name=weights_name,
                         keypoint_confidence=keypoint_confidence,
                         toward_max_degrees=toward_max_degrees, away_min_degrees=away_min_degrees,
                         min_facing_length=min_facing_length,
                         min_stable_samples=min_stable_samples, max_gap_seconds=max_gap_seconds,
                         match_iou_min=match_iou_min, standing_min_ratio=standing_min_ratio,
                         sitting_max_ratio=sitting_max_ratio, max_camera_shift=max_camera_shift,
                         posture_min_stable_samples=posture_min_stable_samples,
                         posture_max_gap_seconds=posture_max_gap_seconds)
    return run_pass(Path(video_path), data, [job], detector=detector,
                    frame_reader_factory=frame_reader_factory, progress=progress)[0]
