"""Plan identity-gated movement windows from a finished tracking candidate.

Pure logic over ``observations.pending.json``: no decoding, no inference, no
provider. Windows never cross a frame that the dense causal audit marks as
uncertain or a change of tracker binding, and they tile the decoded session
without gaps so unread time stays explicit.
"""

import hashlib
import json
import math
from pathlib import Path


MAX_CANDIDATE_BYTES = 20 * 1024 * 1024
MAX_WINDOWS = 10000
IDENTITIES = frozenset({'confirmed', 'uncertain'})
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _track_id(value):
    return type(value) is int and value >= 0


def _box(value):
    return (isinstance(value, list) and len(value) == 4
            and all(_finite_number(coordinate) and 0 <= coordinate <= 1 for coordinate in value)
            and value[0] < value[2] and value[1] < value[3])


def _validate_candidate(data):
    source = data.get('source') if isinstance(data, dict) else None
    provenance = data.get('provenance') if isinstance(data, dict) else None
    if (data.get('schema_version') != 1 or data.get('mode') != 'precomputed'
            or not isinstance(source, dict) or not isinstance(provenance, dict)):
        return False
    sha, fps, duration = source.get('sha256'), source.get('fps'), source.get('duration')
    decoded, frame_count = source.get('decoded_frame_count'), source.get('frame_count')
    quality, audit = provenance.get('quality'), provenance.get('causal_audit')
    observations = data.get('observations')
    if (not isinstance(sha, str) or len(sha) != 64 or not set(sha) <= _SHA_CHARACTERS
            or provenance.get('sha256') != sha
            or not _finite_number(fps) or fps <= 0
            or not _finite_number(duration) or duration <= 0
            or type(decoded) is not int or type(frame_count) is not int
            or not 0 < decoded <= frame_count
            or not isinstance(quality, dict) or quality.get('passed') is not True
            or not isinstance(audit, list) or len(audit) != decoded
            or not isinstance(observations, list)):
        return False
    for index, row in enumerate(audit):
        if (not isinstance(row, dict) or row.get('frame_index') != index
                or not _finite_number(row.get('time')) or row['time'] != index / fps
                or row.get('identity') not in IDENTITIES
                or row['identity'] == 'confirmed' and not _track_id(row.get('target_id'))):
            return False
    frame_of_time = {row['time']: row['frame_index'] for row in audit}
    for row in observations:
        if not isinstance(row, dict) or row.get('identity') not in IDENTITIES:
            return False
        boxes = row.get('boxes')
        if (not isinstance(boxes, list)
                or any(not isinstance(box, dict) or not _box(box.get('xyxy'))
                       or box.get('id') is not None and not _track_id(box.get('id'))
                       for box in boxes)):
            return False
        if row['identity'] != 'confirmed':
            continue
        index = frame_of_time.get(row.get('time')) if _finite_number(row.get('time')) else None
        if index is None:
            return False
        audit_row = audit[index]
        if (audit_row['identity'] != 'confirmed'
                or row.get('target_id') != audit_row['target_id']
                or sum(box.get('id') == row['target_id'] for box in boxes) != 1):
            return False
    return True


def load_tracking_candidate(path):
    """Return ``(data, sha256)`` for one quality-passed candidate with a dense audit."""
    try:
        with Path(path).open('rb') as handle:
            raw = handle.read(MAX_CANDIDATE_BYTES + 1)
        if len(raw) > MAX_CANDIDATE_BYTES:
            raise ValueError
        data = json.loads(raw.decode('utf-8'))
        if not _validate_candidate(data):
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
        raise ValueError('invalid_tracking_candidate') from None
    return data, hashlib.sha256(raw).hexdigest()


def decoded_seconds(data):
    """End of the decoded session on the tracker's nominal-FPS time basis."""
    source = data['source']
    return min(source['decoded_frame_count'] / source['fps'], source['duration'])


def _overlap(a, b):
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / area if area > 0 else 0.0


def _target_samples(data):
    """Map frame index -> (target_id, target box, max overlap, other people's boxes)."""
    frame_of_time = {row['time']: row['frame_index']
                     for row in data['provenance']['causal_audit']}
    samples = {}
    for row in data['observations']:
        if row['identity'] != 'confirmed':
            continue
        index = frame_of_time[row['time']]
        target = [box for box in row['boxes'] if box.get('id') == row['target_id']][0]
        others = [list(box['xyxy']) for box in row['boxes'] if box is not target]
        overlap = max([_overlap(target['xyxy'], box) for box in others] or [0.0])
        samples[index] = (row['target_id'], list(target['xyxy']), overlap, others)
    return samples


def _runs(audit):
    """Maximal spans of one identity state and, when confirmed, one tracker binding."""
    runs, start = [], 0
    for index in range(1, len(audit) + 1):
        if index == len(audit) or _run_key(audit[index]) != _run_key(audit[start]):
            runs.append((start, index - 1, _run_key(audit[start])))
            start = index
    return runs


def _run_key(row):
    return (True, row['target_id']) if row['identity'] == 'confirmed' else (False, None)


def plan_movement_windows(data, *, target_window_seconds=2.0, min_window_seconds=1.0,
                          frames_per_window=4):
    """Tile decoded frames into identity-gated windows with evenly spaced target samples.

    Confirmed runs shorter than ``min_window_seconds`` are ``too_short``; longer runs
    are split into equal windows no longer than ``target_window_seconds``. Eligible
    windows need at least two sampled frames with exactly one target box.
    """
    if (not _finite_number(target_window_seconds) or not 0.5 <= target_window_seconds <= 5
            or not _finite_number(min_window_seconds)
            or not 0 < min_window_seconds <= target_window_seconds / 2
            or type(frames_per_window) is not int or not 2 <= frames_per_window <= 4):
        raise ValueError('invalid_window_parameters')
    source = data['source']
    fps, audit = source['fps'], data['provenance']['causal_audit']
    end_of_session = decoded_seconds(data)
    samples = _target_samples(data)
    spans = []
    for start, end, (confirmed, target_id) in _runs(audit):
        length = end - start + 1
        if not confirmed:
            spans.append((start, end, 'identity_uncertain', None))
        elif length / fps < min_window_seconds:
            spans.append((start, end, 'too_short', target_id))
        else:
            count = max(1, math.ceil(length / (target_window_seconds * fps) - 1e-9))
            bounds = [start + round(part * length / count) for part in range(count + 1)]
            spans.extend((first, following - 1, 'eligible', target_id)
                         for first, following in zip(bounds, bounds[1:]))
    if len(spans) > MAX_WINDOWS:
        raise ValueError('too_many_windows')
    windows = []
    for number, (start, end, status, target_id) in enumerate(spans):
        available = [index for index in range(start, end + 1)
                     if index in samples and samples[index][0] == target_id]
        overlap = (max(samples[index][2] for index in available)
                   if available and status != 'identity_uncertain' else None)
        frames = []
        if status == 'eligible':
            if len(available) < 2:
                status = 'insufficient_frames'
            else:
                count = min(frames_per_window, len(available))
                picks = [available[round(part * (len(available) - 1) / (count - 1))]
                         for part in range(count)]
                frames = [{'frame_index': index, 'time': audit[index]['time'],
                           'target_box': list(samples[index][1]),
                           'other_boxes': [list(box) for box in samples[index][3]]}
                          for index in picks]
        windows.append({
            'segment_id': f'mov-{number:06d}', 'status': status,
            'start_frame': start, 'end_frame': end,
            'start_time': start / fps,
            'end_time': end_of_session if end == len(audit) - 1 else (end + 1) / fps,
            'target_id': target_id, 'max_other_overlap': overlap, 'frames': frames,
        })
    return windows
