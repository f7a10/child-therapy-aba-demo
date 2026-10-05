"""Pure orientation features: is the child's head turned toward the task region?

An observable 2D sign only, never attention, gaze or intent. The head centre is
the midpoint of the visible ears (one visible ear in profile is the centre); the
facing vector runs from it to the nose. Its angle to the direction from the head
centre to the centre of the therapist-drawn task region decides the state, with
a gray band between ``toward`` and ``away`` where the state is ``unclear``. A
facing vector that is short relative to the head-to-shoulders distance (head
squarely to or from the camera) is also ``unclear``. A missing nose, ears or
shoulders, or a head inside the region, is ``not_measurable``, never ``away``.

Angles are measured in pixel space (``aspect`` = image width / height). Two
gates make every other sample ``not_measurable``: the stable posture of the
same skeleton (posture-channel rule over leg ratios, causal) must be sitting, and the background camera translation since the
previous 5 Hz sample must be reliably estimated and at most ``MAX_CAMERA_SHIFT``
frame heights, because the fixed region is only meaningful under a still
camera. Zoom (scale change) is not gated. Thresholds are provisional, set on
two development recordings.

Version 2 readings add the work area: the share of the tracked child box that
lies inside the drawn region. At least ``AREA_AT_MIN`` is ``at_area``, at most
``AREA_AWAY_MAX`` is ``away_from_area``, in between ``unclear``. It needs no
keypoints (only the tracked box), so it is measurable whenever the child is
identified and the camera is still (same camera gate as the head). It says where
the body is, never what the child is doing there.

Version 3 readings make the work area follow the camera and measure distance.
The drawn region is placed in each frame by matching that frame's background
directly to the frame it was drawn on (so small errors never add up); only
when that match fails is it carried from the previous frame by the camera step.
A handheld or panning camera so keeps it on the table. The state comes from the gap between the
child box and the region, in child-box heights: touching or overlapping (at most
``AREA_NEAR_MAX``) is ``at_area``, at least ``AREA_AWAY_MIN`` away is
``away_from_area``, in between ``unclear``. Standing up next to the seat is not
leaving the area (the posture channel reports that); walking off is. A step with
no camera estimate, or a region carried out of the frame, is not measurable.
"""

import math

from .posture_features import (
    MAX_GAP_SECONDS as POSTURE_MAX_GAP_SECONDS, MIN_STABLE_SAMPLES as POSTURE_MIN_STABLE_SAMPLES,
    SITTING_MAX_RATIO, STANDING_MIN_RATIO, classify_posture)


NOSE, EARS, SHOULDERS = 0, (3, 4), (5, 6)
KEYPOINT_CONFIDENCE = 0.5
TOWARD_MAX_DEGREES = 60.0
AWAY_MIN_DEGREES = 100.0
MIN_FACING_LENGTH = 0.25
MIN_NECK = 1e-3
MIN_REGION_SIZE = 0.02
MAX_CAMERA_SHIFT = 0.015
MIN_STABLE_SAMPLES = 3
MAX_GAP_SECONDS = 3.0
ORIENTATION_STATES = ('toward', 'away', 'unclear', 'not_measurable')
EVENT_KINDS = {('toward', 'away'): 'turned_away_from_task',
               ('away', 'toward'): 'turned_back_to_task'}
AREA_AT_MIN = 0.25
AREA_AWAY_MAX = 0.10
AREA_STATES = ('at_area', 'away_from_area', 'unclear', 'not_measurable')
AREA_EVENT_KINDS = {('at_area', 'away_from_area'): 'left_work_area',
                    ('away_from_area', 'at_area'): 'returned_to_work_area'}
AREA_NEAR_MAX = 0.05
AREA_AWAY_MIN = 0.30
# A step between neighbouring samples that changes scale more than this, or moves
# more than a frame height, is treated as unknown rather than followed; a match to
# the drawing frame may zoom and move more.
MAX_FOLLOW_SCALE_CHANGE = 0.25
MAX_FOLLOW_SHIFT = 1.0
MAX_REFERENCE_SCALE_CHANGE = 0.6
MAX_REFERENCE_SHIFT = 1.5
MIN_REGION_IN_FRAME = 0.5


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_task_region(region):
    """True for a normalized ``[x1, y1, x2, y2]`` inside [0, 1] with a minimal size."""
    return (isinstance(region, list) and len(region) == 4
            and all(_finite(value) and 0 <= value <= 1 for value in region)
            and region[2] - region[0] >= MIN_REGION_SIZE
            and region[3] - region[1] >= MIN_REGION_SIZE)


def _mean(points, indices, minimum, aspect):
    visible = [points[index] for index in indices if points[index][2] >= minimum]
    if not visible:
        return None
    return (sum(point[0] for point in visible) / len(visible) * aspect,
            sum(point[1] for point in visible) / len(visible))


def facing_measure(points, task_region, *, aspect=1.0, keypoint_confidence=KEYPOINT_CONFIDENCE):
    """Return (angle in degrees to the region centre, facing length / neck), or (None, None)."""
    if (not isinstance(points, list) or len(points) != 17
            or any(not isinstance(point, (list, tuple)) or len(point) < 3
                   or not all(_finite(value) for value in point[:3]) for point in points)
            or not valid_task_region(task_region) or not _finite(aspect) or aspect <= 0):
        return None, None
    nose = _mean(points, (NOSE,), keypoint_confidence, aspect)
    centre = _mean(points, EARS, keypoint_confidence, aspect)
    shoulders = _mean(points, SHOULDERS, keypoint_confidence, aspect)
    if nose is None or centre is None or shoulders is None:
        return None, None
    x1, y1, x2, y2 = task_region
    if x1 * aspect <= centre[0] <= x2 * aspect and y1 <= centre[1] <= y2:
        return None, None
    neck = math.dist(centre, shoulders)
    facing = (nose[0] - centre[0], nose[1] - centre[1])
    target = ((x1 + x2) / 2 * aspect - centre[0], (y1 + y2) / 2 - centre[1])
    if neck < MIN_NECK or math.hypot(*facing) == 0:
        return None, None
    angle = math.degrees(abs(math.atan2(facing[0] * target[1] - facing[1] * target[0],
                                        facing[0] * target[0] + facing[1] * target[1])))
    return angle, math.hypot(*facing) / neck


def classify_orientation(angle, length, *, toward_max=TOWARD_MAX_DEGREES,
                         away_min=AWAY_MIN_DEGREES, min_length=MIN_FACING_LENGTH):
    """Map (angle, facing length) to toward / away / unclear / not_measurable."""
    if (not all(_finite(value) for value in (toward_max, away_min, min_length))
            or not 0 < toward_max < away_min < 180 or min_length < 0):
        raise ValueError('invalid_orientation_thresholds')
    if angle is None or length is None:
        return 'not_measurable'
    if length < min_length:
        return 'unclear'
    if angle <= toward_max:
        return 'toward'
    if angle >= away_min:
        return 'away'
    return 'unclear'


def camera_shift(step):
    """Translation magnitude (height units) of a ``[a, b, tx, c, d, ty]`` camera step, or None."""
    if (not isinstance(step, (list, tuple)) or len(step) != 6
            or not all(_finite(value) for value in step)):
        return None
    return math.hypot(step[2], step[5])


def stable_seated(samples, *, min_stable_samples=POSTURE_MIN_STABLE_SAMPLES,
                  max_gap_seconds=POSTURE_MAX_GAP_SECONDS, standing_min=STANDING_MIN_RATIO,
                  sitting_max=SITTING_MAX_RATIO):
    """Causal per-sample flag: is the stable posture (posture-channel rule) ``sitting``?

    ``samples`` are time-ordered ``{'time', 'identity', 'leg_ratio'}``. A posture
    becomes stable after ``min_stable_samples`` consecutive measured standing /
    sitting samples agree; unclear or missing leg ratios neither confirm nor break
    it, so a seated child whose knees are hidden for a while stays seated until
    standing is confirmed. An identity gap, or more than ``max_gap_seconds`` since
    the last measured posture, forgets it. Each flag uses only samples up to itself.
    """
    if (type(min_stable_samples) is not int or not 2 <= min_stable_samples <= 20
            or not _finite(max_gap_seconds) or not 0 < max_gap_seconds <= 60):
        raise ValueError('invalid_orientation_parameters')
    flags = []
    stable = candidate = last_measured_time = None
    candidate_count = 0
    for sample in samples:
        if sample['identity'] != 'confirmed':
            stable = candidate = last_measured_time = None
            flags.append(False)
            continue
        time = sample['time']
        if last_measured_time is not None and time - last_measured_time > max_gap_seconds:
            stable = candidate = last_measured_time = None
        posture = classify_posture(sample['leg_ratio'], standing_min=standing_min,
                                   sitting_max=sitting_max)
        if posture in ('standing', 'sitting'):
            last_measured_time = time
            if posture == stable:
                candidate = None
            else:
                if posture != candidate:
                    candidate, candidate_count = posture, 0
                candidate_count += 1
                if candidate_count >= min_stable_samples:
                    stable, candidate = posture, None
        flags.append(stable == 'sitting')
    return flags


def orientation_state(angle, length, seated, shift, *, toward_max=TOWARD_MAX_DEGREES,
                      away_min=AWAY_MIN_DEGREES, min_length=MIN_FACING_LENGTH,
                      max_camera_shift=MAX_CAMERA_SHIFT):
    """Head state, gated: only a stably seated child under a still camera.

    The fixed task region is only meaningful while the camera is still and the
    child sits at the task; otherwise (not stably seated, no reliable camera
    estimate, or a camera step above ``max_camera_shift``) the state is
    ``not_measurable``.
    """
    if not _finite(max_camera_shift) or max_camera_shift <= 0:
        raise ValueError('invalid_orientation_thresholds')
    head = classify_orientation(angle, length, toward_max=toward_max, away_min=away_min,
                                min_length=min_length)
    if seated is not True or not _finite(shift) or not 0 <= shift <= max_camera_shift:
        return 'not_measurable'
    return head


def orientation_states(samples, config):
    """Recompute every sample's state (None for uncertain identity) from its measures."""
    seated = stable_seated(samples, min_stable_samples=config['posture_min_stable_samples'],
                           max_gap_seconds=config['posture_max_gap_seconds'],
                           standing_min=config['standing_min_ratio'],
                           sitting_max=config['sitting_max_ratio'])
    return [None if sample['identity'] != 'confirmed' else orientation_state(
        sample['facing_angle'], sample['facing_length'], flag, sample['camera_shift'],
        toward_max=config['toward_max_degrees'], away_min=config['away_min_degrees'],
        min_length=config['min_facing_length'], max_camera_shift=config['max_camera_shift'])
        for sample, flag in zip(samples, seated)]


def area_overlap(box, task_region):
    """Share of the child box ``[x1, y1, x2, y2]`` inside the task region, or None."""
    if (not isinstance(box, (list, tuple)) or len(box) != 4 or not all(_finite(v) for v in box)
            or box[2] <= box[0] or box[3] <= box[1] or not valid_task_region(task_region)):
        return None
    width = max(0.0, min(box[2], task_region[2]) - max(box[0], task_region[0]))
    height = max(0.0, min(box[3], task_region[3]) - max(box[1], task_region[1]))
    return width * height / ((box[2] - box[0]) * (box[3] - box[1]))


def follow_region(region, step, aspect, *, max_scale_change=MAX_FOLLOW_SCALE_CHANGE,
                  max_shift=MAX_FOLLOW_SHIFT):
    """The region moved by one camera step (frame-height units, x scaled by ``aspect``).

    Returns None when the step is missing or not plausible (the region is then
    unknown for this sample, but the caller may keep the previous one).
    """
    if (not isinstance(step, (list, tuple)) or len(step) != 6 or not all(_finite(v) for v in step)
            or not _finite(aspect) or aspect <= 0):
        return None
    a, b, tx, c, d, ty = step
    if abs(math.hypot(a, c) - 1.0) > max_scale_change or math.hypot(tx, ty) > max_shift:
        return None
    corners = [(x * aspect, y) for x in (region[0], region[2]) for y in (region[1], region[3])]
    moved = [(a * x + b * y + tx, c * x + d * y + ty) for x, y in corners]
    xs, ys = [x / aspect for x, _ in moved], [y for _, y in moved]
    return [min(xs), min(ys), max(xs), max(ys)]


def region_in_frame(region):
    """Share of the region's area that lies inside the frame (0 to 1)."""
    width, height = region[2] - region[0], region[3] - region[1]
    if width <= 0 or height <= 0:
        return 0.0
    inside = (max(0.0, min(1.0, region[2]) - max(0.0, region[0]))
              * max(0.0, min(1.0, region[3]) - max(0.0, region[1])))
    return inside / (width * height)


def area_gap(box, region):
    """Distance between the child box and the region in child-box heights (0 when touching)."""
    if (not isinstance(box, (list, tuple)) or len(box) != 4 or not all(_finite(v) for v in box)
            or box[2] <= box[0] or box[3] <= box[1]):
        return None
    dx = max(region[0] - box[2], box[0] - region[2], 0.0)
    dy = max(region[1] - box[3], box[1] - region[3], 0.0)
    return math.hypot(dx, dy) / (box[3] - box[1])


def area_state_v3(gap, *, near_max=AREA_NEAR_MAX, away_min=AREA_AWAY_MIN):
    """Work-area state from the distance to the (camera-followed) region."""
    if not all(_finite(value) for value in (near_max, away_min)) or not 0 <= near_max < away_min:
        raise ValueError('invalid_orientation_thresholds')
    if gap is None:
        return 'not_measurable'
    if gap <= near_max:
        return 'at_area'
    if gap >= away_min:
        return 'away_from_area'
    return 'unclear'


def area_state(overlap, shift, *, at_min=AREA_AT_MIN, away_max=AREA_AWAY_MAX,
               max_camera_shift=MAX_CAMERA_SHIFT):
    """Work-area state under a still camera; ``not_measurable`` otherwise."""
    if (not all(_finite(value) for value in (at_min, away_max, max_camera_shift))
            or not 0 <= away_max < at_min <= 1 or max_camera_shift <= 0):
        raise ValueError('invalid_orientation_thresholds')
    if overlap is None or not _finite(shift) or not 0 <= shift <= max_camera_shift:
        return 'not_measurable'
    if overlap >= at_min:
        return 'at_area'
    if overlap <= away_max:
        return 'away_from_area'
    return 'unclear'


def area_states(samples, config):
    """Recompute every sample's work-area state (None for uncertain identity)."""
    if 'area_near_max' in config:  # version 3: distance to the camera-followed region
        return [None if sample['identity'] != 'confirmed' else area_state_v3(
            sample['area_gap'], near_max=config['area_near_max'], away_min=config['area_away_min'])
            for sample in samples]
    return [None if sample['identity'] != 'confirmed' else area_state(
        sample['area_overlap'], sample['camera_shift'], at_min=config['area_at_min'],
        away_max=config['area_away_max'], max_camera_shift=config['max_camera_shift'])
        for sample in samples]


def orientation_events_v2(samples, *, min_stable_samples=MIN_STABLE_SAMPLES,
                          max_gap_seconds=MAX_GAP_SECONDS):
    """Head turns and work-area changes, in time order (each under the same stable rule)."""
    events = (orientation_events(samples, min_stable_samples=min_stable_samples,
                                 max_gap_seconds=max_gap_seconds)
              + orientation_events(samples, min_stable_samples=min_stable_samples,
                                   max_gap_seconds=max_gap_seconds, key='area_state',
                                   kinds=AREA_EVENT_KINDS))
    return sorted(events, key=lambda event: (event['start_time'], event['end_time'], event['kind']))


def orientation_events(samples, *, min_stable_samples=MIN_STABLE_SAMPLES,
                       max_gap_seconds=MAX_GAP_SECONDS, key='state', kinds=EVENT_KINDS):
    """Turns between stable toward / away states inside continuous confirmed identity.

    Same rule as posture: a state is stable after ``min_stable_samples``
    consecutive measured samples agree; unclear / not_measurable neither confirm
    nor break the count. An identity gap or more than ``max_gap_seconds``
    without a measured state forgets the stable state. Each event cites the last
    old-state sample and the first new-state sample; ``detected_time`` is the
    confirming sample. ``key`` and ``kinds`` pick the state series (head by default).
    """
    measured = {state for pair in kinds for state in pair}
    if (type(min_stable_samples) is not int or not 2 <= min_stable_samples <= 20
            or not _finite(max_gap_seconds) or not 0 < max_gap_seconds <= 60):
        raise ValueError('invalid_orientation_parameters')
    events = []
    stable = stable_last_time = None
    candidate = candidate_first_time = None
    candidate_count = 0
    last_measured_time = None
    for sample in samples:
        if sample['identity'] != 'confirmed':
            stable = candidate = last_measured_time = None
            continue
        state = sample[key]
        if state not in measured:
            continue
        time = sample['time']
        if last_measured_time is not None and time - last_measured_time > max_gap_seconds:
            stable = candidate = None
        last_measured_time = time
        if state == stable:
            stable_last_time = time
            candidate = None
            continue
        if state != candidate:
            candidate, candidate_first_time, candidate_count = state, time, 0
        candidate_count += 1
        if candidate_count >= min_stable_samples:
            if stable is not None:
                events.append({'kind': kinds[(stable, candidate)],
                               'start_time': stable_last_time, 'end_time': candidate_first_time,
                               'evidence_times': [stable_last_time, candidate_first_time],
                               'detected_time': time})
            stable, stable_last_time, candidate = candidate, time, None
    return events
