"""Local posture reading of the selected child over a recorded session.

Consumes a finished, quality-passed tracking candidate and its exact source
video. For every confirmed 5 Hz sample it runs a local pose detector on that
frame and keeps only the detection that overlaps the tracked child box; another
person's skeleton is never substituted. Writes a pending, source- and
tracking-bound posture document. Nothing leaves the machine; pose ``signals``
in the tracking candidate are never changed.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path

from .channel_pass import check_output_dir, load_bound_candidate, run_pass
from .colab_workflow import _write_bytes
from .movement_frames import SequentialFrameReader
from .movement_windows import decoded_seconds
from .posture_features import (
    EVENT_KINDS_V2, HOLD_MAX_HIP_SHIFT, HOLD_MAX_IDENTITY_GAP, KEYPOINT_CONFIDENCE, LYING_MIN_DEGREES,
    LYING_MIN_THIGH_DEGREES, MAX_GAP_SECONDS,
    MIN_STABLE_SAMPLES, SITTING_MAX_RATIO, STANDING_MIN_RATIO, body_measures, classify_posture_v2,
    gap_reason, held_postures, leg_ratio, posture_events)
from .posture_schema import encode_posture_document


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MATCH_IOU_MIN = 0.5


class YoloPoseDetector:
    """Local Ultralytics pose detector returning normalized boxes and keypoints."""

    def __init__(self, weights, *, device=None, imgsz=640, confidence=0.25):
        from ultralytics import YOLO

        self.weights = str(weights)
        self._model = YOLO(self.weights)
        self._options = {'verbose': False, 'conf': confidence, 'imgsz': imgsz}
        if device is not None:
            self._options['device'] = device

    def detect(self, image):
        import numpy

        frame = numpy.asarray(image.convert('RGB'))[:, :, ::-1]
        result = self._model.predict(frame, **self._options)[0]
        if result.boxes is None or result.keypoints is None:
            return []
        width, height = image.size
        detections = []
        for box, points in zip(result.boxes.xyxy.cpu().tolist(),
                               result.keypoints.data.cpu().tolist()):
            detections.append({
                'xyxy': [box[0] / width, box[1] / height, box[2] / width, box[3] / height],
                'keypoints': [[x / width, y / height, confidence] for x, y, confidence in points],
            })
        return detections


def _iou(a, b):
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - width * height
    return width * height / union if union > 0 else 0.0


def _child_keypoints(detections, target_box, match_iou_min):
    """Keypoints of the detection that best matches the tracked child box, or None."""
    scored = [(_iou(target_box, detection['xyxy']), detection) for detection in detections]
    if not scored:
        return None
    score, detection = max(scored, key=lambda item: item[0])
    return detection['keypoints'] if score >= match_iou_min else None


class PostureJob:
    """Posture over the samples of one pass (see ``channel_pass``)."""
    PENDING, REPORT = 'posture.pending.json', 'posture-report.json'

    def __init__(self, data, tracking_sha, output_dir, *, weights_name='yolo11s-pose.pt',
                 keypoint_confidence=KEYPOINT_CONFIDENCE, standing_min_ratio=STANDING_MIN_RATIO,
                 sitting_max_ratio=SITTING_MAX_RATIO, min_stable_samples=MIN_STABLE_SAMPLES,
                 max_gap_seconds=MAX_GAP_SECONDS, match_iou_min=MATCH_IOU_MIN,
                 standing_needs_both_knees=True, lying_min_degrees=LYING_MIN_DEGREES,
                 lying_min_thigh_degrees=LYING_MIN_THIGH_DEGREES,
                 hold_max_hip_shift=HOLD_MAX_HIP_SHIFT, hold_max_identity_gap=HOLD_MAX_IDENTITY_GAP):
        self.data, self.tracking_sha, self.output_dir = data, tracking_sha, Path(output_dir)
        self.config = {'weights': weights_name, 'keypoint_confidence': keypoint_confidence,
                       'standing_min_ratio': standing_min_ratio,
                       'sitting_max_ratio': sitting_max_ratio,
                       'min_stable_samples': min_stable_samples,
                       'max_gap_seconds': max_gap_seconds, 'match_iou_min': match_iou_min,
                       'standing_needs_both_knees': standing_needs_both_knees,
                       'lying_min_degrees': lying_min_degrees,
                       'lying_min_thigh_degrees': lying_min_thigh_degrees,
                       'hold_max_hip_shift': hold_max_hip_shift,
                       'hold_max_identity_gap': hold_max_identity_gap}
        self.samples = []

    def step(self, number, row, index, frame, context):
        config = self.config
        if row['identity'] != 'confirmed':
            self.samples.append({'time': row['time'], 'frame_index': index,
                                 'identity': 'uncertain', 'state': None, 'leg_ratio': None,
                                 'torso_angle': None, 'thigh_angle': None, 'hip_y': None,
                                 'torso': None,
                                 'reason': None, 'held': None})
            return
        target = [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']][0]
        points = _child_keypoints(frame.detections(), target, config['match_iou_min'])
        width, height = frame.image.size
        ratio = leg_ratio(points, keypoint_confidence=config['keypoint_confidence'],
                          standing_needs_both_knees=config['standing_needs_both_knees'],
                          standing_min=config['standing_min_ratio'])
        angle, thigh, hip, torso = body_measures(points, aspect=width / height,
                                                 keypoint_confidence=config['keypoint_confidence'])
        state = classify_posture_v2(ratio, angle, thigh, standing_min=config['standing_min_ratio'],
                                    sitting_max=config['sitting_max_ratio'],
                                    lying_min=config['lying_min_degrees'],
                                    lying_min_thigh=config['lying_min_thigh_degrees'])
        reason = (gap_reason(points, keypoint_confidence=config['keypoint_confidence'])
                  if state == 'not_measurable' else None)
        self.samples.append({'time': row['time'], 'frame_index': index, 'identity': 'confirmed',
                             'state': state, 'leg_ratio': ratio, 'torso_angle': angle,
                             'thigh_angle': thigh,
                             'hip_y': hip, 'torso': torso, 'reason': reason, 'held': None})

    def finish(self):
        data, samples, config = self.data, self.samples, self.config
        source = data['source']
        for sample, held in zip(samples, held_postures(
                samples, min_stable_samples=config['min_stable_samples'],
                max_hip_shift=config['hold_max_hip_shift'],
                max_identity_gap=config['hold_max_identity_gap'])):
            sample['held'] = held
        events = [{'event_id': f'pos-{number:06d}', **event, 'clinician_confirmation': 'pending'}
                  for number, event in enumerate(posture_events(
                      samples, min_stable_samples=config['min_stable_samples'],
                      max_gap_seconds=config['max_gap_seconds'], kinds=EVENT_KINDS_V2))]
        document = {'schema_version': 2, 'kind': 'posture_reading',
                    'source_sha256': source['sha256'],
                    'tracking_candidate_sha256': self.tracking_sha, 'config': config,
                    'decoded_seconds': decoded_seconds(data), 'samples': samples,
                    'events': events}
        encoded = encode_posture_document(document, source['duration'])
        report = {
            'posture_candidate_sha256': hashlib.sha256(encoded).hexdigest(),
            'tracking_candidate_sha256': self.tracking_sha, 'source_sha256': source['sha256'],
            'state_counts': dict(sorted(Counter(sample['state'] or 'identity_uncertain'
                                                for sample in samples).items())),
            'held_counts': dict(sorted(Counter(sample['held'] for sample in samples
                                               if sample['held']).items())),
            'event_counts': dict(sorted(Counter(event['kind'] for event in events).items())),
        }
        write_job_output(self.output_dir, self.PENDING, encoded, self.REPORT, report)
        return report


def write_job_output(output_dir, pending_name, encoded, report_name, report):
    """Write a pending document and its count report; never leave half of the pair."""
    pending, report_path = output_dir / pending_name, output_dir / report_name
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        _write_bytes(pending, encoded)
        _write_bytes(report_path, json.dumps(report, sort_keys=True, indent=1).encode('utf-8'))
    except BaseException:
        pending.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise


def read_posture(video_path, candidate_path, output_dir, *, detector, weights_name='yolo11s-pose.pt',
                 keypoint_confidence=KEYPOINT_CONFIDENCE, standing_min_ratio=STANDING_MIN_RATIO,
                 sitting_max_ratio=SITTING_MAX_RATIO, min_stable_samples=MIN_STABLE_SAMPLES,
                 max_gap_seconds=MAX_GAP_SECONDS, match_iou_min=MATCH_IOU_MIN,
                 standing_needs_both_knees=True,
                 frame_reader_factory=SequentialFrameReader, progress=None,
                 repository_root=REPOSITORY_ROOT):
    """Write ``posture.pending.json`` and ``posture-report.json``; return counts only."""
    output_dir = check_output_dir(output_dir, (PostureJob.PENDING, PostureJob.REPORT),
                                  repository_root, 'posture_candidate_exists')
    data, tracking_sha = load_bound_candidate(video_path, candidate_path)
    job = PostureJob(data, tracking_sha, output_dir, weights_name=weights_name,
                     keypoint_confidence=keypoint_confidence,
                     standing_min_ratio=standing_min_ratio, sitting_max_ratio=sitting_max_ratio,
                     min_stable_samples=min_stable_samples, max_gap_seconds=max_gap_seconds,
                     match_iou_min=match_iou_min,
                     standing_needs_both_knees=standing_needs_both_knees)
    return run_pass(Path(video_path), data, [job], detector=detector,
                    frame_reader_factory=frame_reader_factory, progress=progress)[0]
