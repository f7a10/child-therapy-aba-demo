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

from .colab_workflow import _write_bytes
from .export import file_sha256
from .movement_frames import SequentialFrameReader
from .movement_windows import decoded_seconds, load_tracking_candidate
from .posture_features import (
    KEYPOINT_CONFIDENCE, MAX_GAP_SECONDS, MIN_STABLE_SAMPLES, SITTING_MAX_RATIO,
    STANDING_MIN_RATIO, classify_posture, leg_ratio, posture_events)
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


def read_posture(video_path, candidate_path, output_dir, *, detector, weights_name='yolo11s-pose.pt',
                 keypoint_confidence=KEYPOINT_CONFIDENCE, standing_min_ratio=STANDING_MIN_RATIO,
                 sitting_max_ratio=SITTING_MAX_RATIO, min_stable_samples=MIN_STABLE_SAMPLES,
                 max_gap_seconds=MAX_GAP_SECONDS, match_iou_min=MATCH_IOU_MIN,
                 frame_reader_factory=SequentialFrameReader, progress=None,
                 repository_root=REPOSITORY_ROOT):
    """Write ``posture.pending.json`` and ``posture-report.json``; return counts only."""
    video_path, output_dir = Path(video_path), Path(output_dir).resolve()
    if output_dir.is_relative_to(Path(repository_root).resolve()):
        raise ValueError('output_inside_repository')
    pending = output_dir / 'posture.pending.json'
    report_path = output_dir / 'posture-report.json'
    if pending.exists() or report_path.exists():
        raise ValueError('posture_candidate_exists')
    data, tracking_sha = load_tracking_candidate(candidate_path)
    source = data['source']
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_does_not_match_tracking_candidate')
    config = {'weights': weights_name, 'keypoint_confidence': keypoint_confidence,
              'standing_min_ratio': standing_min_ratio, 'sitting_max_ratio': sitting_max_ratio,
              'min_stable_samples': min_stable_samples, 'max_gap_seconds': max_gap_seconds,
              'match_iou_min': match_iou_min}
    frame_of_time = {row['time']: row['frame_index'] for row in data['provenance']['causal_audit']}
    rows = sorted(data['observations'], key=lambda row: row['time'])
    samples = []
    reader = frame_reader_factory(video_path)
    try:
        for number, row in enumerate(rows):
            index = frame_of_time[row['time']]
            if samples and index <= samples[-1]['frame_index']:
                raise ValueError('invalid_tracking_candidate')
            if row['identity'] != 'confirmed':
                samples.append({'time': row['time'], 'frame_index': index,
                                'identity': 'uncertain', 'state': None, 'leg_ratio': None})
                continue
            target = [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']][0]
            points = _child_keypoints(detector.detect(reader.read(index)), target, match_iou_min)
            ratio = leg_ratio(points, keypoint_confidence=keypoint_confidence)
            samples.append({'time': row['time'], 'frame_index': index, 'identity': 'confirmed',
                            'state': classify_posture(ratio, standing_min=standing_min_ratio,
                                                      sitting_max=sitting_max_ratio),
                            'leg_ratio': ratio})
            if progress and (number + 1) % 100 == 0:
                progress(number + 1, len(rows))
    finally:
        reader.close()
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_changed_during_reading')
    events = [{'event_id': f'pos-{number:06d}', **event, 'clinician_confirmation': 'pending'}
              for number, event in enumerate(posture_events(
                  samples, min_stable_samples=min_stable_samples,
                  max_gap_seconds=max_gap_seconds))]
    document = {'schema_version': 1, 'kind': 'posture_reading', 'source_sha256': source['sha256'],
                'tracking_candidate_sha256': tracking_sha, 'config': config,
                'decoded_seconds': decoded_seconds(data), 'samples': samples, 'events': events}
    encoded = encode_posture_document(document, source['duration'])
    report = {
        'posture_candidate_sha256': hashlib.sha256(encoded).hexdigest(),
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
