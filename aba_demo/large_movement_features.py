"""Pure large-movement features from the selected child's own pose keypoints.

The body centre is the hip midpoint and the scale is the torso length (shoulder
midpoint to hip midpoint), both in frame-height units so x and y are comparable.
Camera motion between two samples is a partial-affine matrix estimated on the
background; the child's displacement is measured after removing it. A large
movement is a compensated HORIZONTAL centre displacement of more than
``displacement_threshold`` torso lengths within ``window_seconds``, inside one
continuous segment of confirmed identity. Vertical motion (sitting down,
standing up) is left to the posture channel, so it never counts here.

Only a nearly still camera is compensated. A handheld camera that orbits or
translates causes parallax: a near child and the far background move by
different amounts, sometimes in opposite directions, which a 2D image transform
cannot remove. So any step whose background shift exceeds ``MAX_CAMERA_SHIFT``
(frame heights per 5 Hz step) has no camera step: the reader abstains and starts
a new segment, and no displacement is chained across camera motion.
Thresholds are provisional. This only records that the body moved; it never
says why.
"""

import math


SHOULDERS, HIPS = (5, 6), (11, 12)
KEYPOINT_CONFIDENCE = 0.5
MIN_TORSO = 0.02
DISPLACEMENT_THRESHOLD = 1.0
WINDOW_SECONDS = 2.0
MERGE_GAP_SECONDS = 1.0
MAX_GAP_SECONDS = 1.0
MAX_CAMERA_SHIFT = 0.015
MAX_CAMERA_SCALE_CHANGE = 0.10
MAX_EVIDENCE_TIMES = 8
SAMPLE_STATES = ('measured', 'segment_start', 'not_measurable')
EVENT_KIND = 'large_movement'
_EPSILON = 1e-9


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _mean_point(points, indices, minimum, aspect):
    visible = [(points[index][0] * aspect, points[index][1]) for index in indices
               if points[index][2] >= minimum]
    if not visible:
        return None
    return (sum(x for x, _ in visible) / len(visible), sum(y for _, y in visible) / len(visible))


def body_centre(points, *, aspect, keypoint_confidence=KEYPOINT_CONFIDENCE):
    """Return ``{'centre': [x, y], 'torso': length}`` in frame-height units, or None."""
    if not _finite(aspect) or aspect <= 0:
        raise ValueError('invalid_aspect')
    if (not isinstance(points, list) or len(points) != 17
            or any(not isinstance(point, (list, tuple)) or len(point) < 3
                   or not all(_finite(value) for value in point[:3]) for point in points)):
        return None
    shoulder = _mean_point(points, SHOULDERS, keypoint_confidence, aspect)
    hip = _mean_point(points, HIPS, keypoint_confidence, aspect)
    if shoulder is None or hip is None:
        return None
    torso = math.hypot(hip[0] - shoulder[0], hip[1] - shoulder[1])
    if torso < MIN_TORSO:
        return None
    return {'centre': [hip[0], hip[1]], 'torso': torso}


def valid_camera(matrix, *, max_shift=MAX_CAMERA_SHIFT, max_scale_change=MAX_CAMERA_SCALE_CHANGE):
    """True for a finite ``[a, b, tx, c, d, ty]`` camera step within the reliability bounds."""
    if not isinstance(matrix, list) or len(matrix) != 6 or not all(map(_finite, matrix)):
        return False
    a, _, tx, c, _, ty = matrix
    return (abs(math.hypot(a, c) - 1.0) <= max_scale_change
            and math.hypot(tx, ty) <= max_shift)


def _apply(matrix, point):
    a, b, tx, c, d, ty = matrix
    return (a * point[0] + b * point[1] + tx, c * point[0] + d * point[1] + ty)


def sample_states(samples, *, max_gap_seconds=MAX_GAP_SECONDS):
    """Per-sample state; ``None`` for uncertain identity.

    A camera step links a sample to the previous sample with a body centre in the
    same confirmed run, at most ``max_gap_seconds`` earlier. A centre without a
    camera step starts a new segment. Raise when a camera step has no such link.
    """
    states, anchor_time = [], None
    for sample in samples:
        if sample['identity'] != 'confirmed':
            states.append(None)
            anchor_time = None
            continue
        if sample['centre'] is None:
            if sample['camera'] is not None:
                raise ValueError('inconsistent_large_movement_samples')
            states.append('not_measurable')
            continue
        if sample['camera'] is None:
            states.append('segment_start')
        elif anchor_time is None or sample['time'] - anchor_time > max_gap_seconds + _EPSILON:
            raise ValueError('inconsistent_large_movement_samples')
        else:
            states.append('measured')
        anchor_time = sample['time']
    return states


def _evidence(times, start, end):
    inside = [time for time in times if start <= time <= end]
    count = min(MAX_EVIDENCE_TIMES, len(inside))
    if count == 1:
        return inside[:1]
    return sorted({inside[round(part * (len(inside) - 1) / (count - 1))] for part in range(count)})


def _detection(segment, threshold, window_seconds):
    """Minimal (start, end) pair ending at the newest segment point, or None.

    Only the horizontal (x) component counts. The start is the latest earlier
    point more than ``threshold`` torso lengths away horizontally;
    it only counts if no point in between was already that far from it, so a child
    who arrived and stays put does not keep extending the episode.
    """
    time, x, _, _ = segment[-1]
    torso = segment[-1][3]
    for index in range(len(segment) - 2, -1, -1):
        start_time, start_x, _, start_torso = segment[index]
        if time - start_time > window_seconds + _EPSILON:
            return None
        torso = max(torso, start_torso)
        if abs(x - start_x) > threshold * torso:
            scale = start_torso
            for middle in segment[index + 1:-1]:
                scale = max(scale, middle[3])
                if abs(middle[1] - start_x) > threshold * scale:
                    return None
            return start_time, time
    return None


def large_movement_events(samples, *, displacement_threshold=DISPLACEMENT_THRESHOLD,
                          window_seconds=WINDOW_SECONDS, merge_gap_seconds=MERGE_GAP_SECONDS,
                          max_gap_seconds=MAX_GAP_SECONDS):
    """Horizontal large-movement episodes inside continuous confirmed identity.

    ``samples`` are time-ordered ``{'time', 'identity', 'centre', 'torso', 'camera'}``.
    Detections closer than ``merge_gap_seconds`` merge into one episode. A camera
    break (new segment) does not close an open episode: a later detection still joins
    it when the unmeasured stretch bridges the gap, i.e. the first break came within
    ``merge_gap_seconds`` of the episode end and the detection starts within
    ``merge_gap_seconds`` of the last break; measured stillness in between keeps
    them apart. An episode is closed by an identity gap, the end of the samples, or
    once no later detection could still join it; ``detected_time`` is that closing
    sample, the earliest moment a causal display may show the episode.
    """
    if (not _finite(displacement_threshold) or not 0 < displacement_threshold <= 10
            or not _finite(window_seconds) or not 0 < window_seconds <= 10
            or not _finite(merge_gap_seconds) or not 0 <= merge_gap_seconds <= 10
            or not _finite(max_gap_seconds) or not 0 < max_gap_seconds <= 10):
        raise ValueError('invalid_large_movement_parameters')
    states = sample_states(samples, max_gap_seconds=max_gap_seconds)
    events, centre_times, segment = [], [], []
    episode = previous_centre = None
    first_break = last_break = None  # camera breaks since the open episode's end

    def close(time):
        nonlocal episode, first_break, last_break
        first_break = last_break = None
        if episode is not None:
            start, end = episode
            events.append({'kind': EVENT_KIND, 'start_time': start, 'end_time': end,
                           'evidence_times': _evidence(centre_times, start, end),
                           'detected_time': time})
            episode = None

    for sample, state in zip(samples, states):
        time = sample['time']
        if episode is not None and time - episode[1] > window_seconds + merge_gap_seconds + _EPSILON:
            close(time)
        if state is None:
            close(time)
        if state is None or state == 'segment_start':
            segment, previous_centre = [], None
        if state == 'segment_start' and episode is not None:
            first_break = time if first_break is None else first_break
            last_break = time
        if state is None or state == 'not_measurable':
            continue
        centre_times.append(time)
        if state == 'segment_start':
            segment = [(time, sample['centre'][0], sample['centre'][1], sample['torso'])]
        else:
            moved_x, moved_y = _apply(sample['camera'], previous_centre)
            _, last_x, last_y, _ = segment[-1]
            segment.append((time, last_x + sample['centre'][0] - moved_x,
                            last_y + sample['centre'][1] - moved_y, sample['torso']))
            found = _detection(segment, displacement_threshold, window_seconds)
            if found is not None:
                start, end = found
                bridged = (first_break is not None
                           and first_break - episode[1] <= merge_gap_seconds + _EPSILON
                           and start - last_break <= merge_gap_seconds + _EPSILON)
                if episode is not None and (
                        start <= episode[1] + merge_gap_seconds + _EPSILON or bridged):
                    episode = (min(episode[0], start), end)
                    first_break = last_break = None
                else:
                    close(time)
                    episode = (start, end)
        previous_centre = sample['centre']
    if episode is not None:
        close(samples[-1]['time'])
    return events


MOTION_WINDOW_SECONDS = 1.0
MOVING_MIN_TORSO = 0.5


def motion_states(samples, *, window_seconds=MOTION_WINDOW_SECONDS, moving_min=MOVING_MIN_TORSO,
                  max_gap_seconds=MAX_GAP_SECONDS):
    """Per sample ``moving`` / ``still`` for the review lane, or None when unknown.

    The camera-compensated body centre (both directions) is compared with where it
    was about ``window_seconds`` earlier in the same segment; a shift of at least
    ``moving_min`` torso lengths is ``moving``. Display data only: events stay the
    stricter horizontal large movements above.
    """
    if (not _finite(window_seconds) or not 0 < window_seconds <= 10
            or not _finite(moving_min) or not 0 < moving_min <= 10):
        raise ValueError('invalid_large_movement_parameters')
    states = sample_states(samples, max_gap_seconds=max_gap_seconds)
    result, segment, previous_centre = [], [], None
    for sample, state in zip(samples, states):
        if state is None or state == 'segment_start':
            segment, previous_centre = [], None
        if state is None or state == 'not_measurable':
            result.append(None)
            continue
        if state == 'segment_start':
            segment = [(sample['time'], sample['centre'][0], sample['centre'][1], sample['torso'])]
        else:
            moved_x, moved_y = _apply(sample['camera'], previous_centre)
            _, last_x, last_y, _ = segment[-1]
            segment.append((sample['time'], last_x + sample['centre'][0] - moved_x,
                            last_y + sample['centre'][1] - moved_y, sample['torso']))
        previous_centre = sample['centre']
        time, x, y, torso = segment[-1]
        earlier = [point for point in segment if time - point[0] <= window_seconds + _EPSILON]
        start = earlier[0]
        if time - start[0] < window_seconds / 2 - _EPSILON:
            result.append(None)
            continue
        shift = math.hypot(x - start[1], y - start[2])
        result.append('moving' if shift >= moving_min * max(torso, start[3]) else 'still')
    return result

