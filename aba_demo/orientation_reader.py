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
import json
from pathlib import Path

from .colab_workflow import _write_bytes
from .export import file_sha256
from .movement_frames import SequentialFrameReader
from .movement_windows import decoded_seconds, load_tracking_candidate
from .orientation_features import (
    AWAY_MIN_DEGREES, KEYPOINT_CONFIDENCE, MAX_CAMERA_SHIFT, MAX_GAP_SECONDS, MIN_FACING_LENGTH,
    MIN_STABLE_SAMPLES, POSTURE_MAX_GAP_SECONDS, POSTURE_MIN_STABLE_SAMPLES, TOWARD_MAX_DEGREES,
    camera_shift, facing_measure, orientation_events, orientation_states, valid_task_region)
from .orientation_schema import encode_orientation_document
from .posture_features import SITTING_MAX_RATIO, STANDING_MIN_RATIO, leg_ratio
from .posture_reader import MATCH_IOU_MIN, YoloPoseDetector, _child_keypoints  # noqa: F401


def _default_motion_estimator():
    from .large_movement_reader import BackgroundMotionEstimator

    return BackgroundMotionEstimator()


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
    task_region = [float(value) for value in task_region]
    video_path, output_dir = Path(video_path), Path(output_dir).resolve()
    if output_dir.is_relative_to(Path(repository_root).resolve()):
        raise ValueError('output_inside_repository')
    pending = output_dir / 'orientation.pending.json'
    report_path = output_dir / 'orientation-report.json'
    if pending.exists() or report_path.exists():
        raise ValueError('orientation_candidate_exists')
    data, tracking_sha = load_tracking_candidate(candidate_path)
    source = data['source']
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_does_not_match_tracking_candidate')
    config = {'weights': weights_name, 'keypoint_confidence': keypoint_confidence,
              'task_region': task_region, 'toward_max_degrees': toward_max_degrees,
              'away_min_degrees': away_min_degrees, 'min_facing_length': min_facing_length,
              'min_stable_samples': min_stable_samples, 'max_gap_seconds': max_gap_seconds,
              'match_iou_min': match_iou_min, 'standing_min_ratio': standing_min_ratio,
              'sitting_max_ratio': sitting_max_ratio, 'max_camera_shift': max_camera_shift,
              'posture_min_stable_samples': posture_min_stable_samples,
              'posture_max_gap_seconds': posture_max_gap_seconds}
    if motion_estimator is None:
        motion_estimator = _default_motion_estimator()
    frame_of_time = {row['time']: row['frame_index'] for row in data['provenance']['causal_audit']}
    rows = sorted(data['observations'], key=lambda row: row['time'])
    samples = []
    previous = None
    reader = frame_reader_factory(video_path)
    try:
        for number, row in enumerate(rows):
            index = frame_of_time[row['time']]
            if samples and index <= samples[-1]['frame_index']:
                raise ValueError('invalid_tracking_candidate')
            image = reader.read(index)
            boxes = [box['xyxy'] for box in row['boxes']]
            shift = (None if previous is None
                     else camera_shift(motion_estimator.estimate(previous[0], previous[1],
                                                                 image, boxes)))
            previous = (image, boxes)
            if row['identity'] != 'confirmed':
                samples.append({'time': row['time'], 'frame_index': index,
                                'identity': 'uncertain', 'state': None,
                                'facing_angle': None, 'facing_length': None,
                                'leg_ratio': None, 'camera_shift': None})
                continue
            target = [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']][0]
            points = _child_keypoints(detector.detect(image), target, match_iou_min)
            width, height = image.size
            angle, length = facing_measure(points, task_region, aspect=width / height,
                                           keypoint_confidence=keypoint_confidence)
            ratio = leg_ratio(points, keypoint_confidence=keypoint_confidence)
            samples.append({'time': row['time'], 'frame_index': index, 'identity': 'confirmed',
                            'state': None, 'facing_angle': angle, 'facing_length': length,
                            'leg_ratio': ratio, 'camera_shift': shift})
            if progress and (number + 1) % 100 == 0:
                progress(number + 1, len(rows))
    finally:
        reader.close()
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_changed_during_reading')
    for sample, state in zip(samples, orientation_states(samples, config)):
        sample['state'] = state
    events = [{'event_id': f'ori-{number:06d}', **event, 'clinician_confirmation': 'pending'}
              for number, event in enumerate(orientation_events(
                  samples, min_stable_samples=min_stable_samples,
                  max_gap_seconds=max_gap_seconds))]
    document = {'schema_version': 1, 'kind': 'orientation_reading',
                'source_sha256': source['sha256'], 'tracking_candidate_sha256': tracking_sha,
                'config': config, 'decoded_seconds': decoded_seconds(data),
                'samples': samples, 'events': events}
    encoded = encode_orientation_document(document, source['duration'])
    report = {
        'orientation_candidate_sha256': hashlib.sha256(encoded).hexdigest(),
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
