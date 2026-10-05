"""Pure posture features from the selected child's own pose keypoints.

The leg ratio is the vertical drop of the knees below the hips divided by the
torso length (shoulders to hips) in image coordinates. Thresholds are
provisional, measured on two development recordings only, and there is a gray
band between them where the state is ``unclear``: the reader never guesses.
Missing joints are ``not_measurable``, never a posture.

Version 2 readings add three things, each from the same skeleton:

* ``lying``: the shoulder-to-hip line is between ``LYING_MIN_DEGREES`` and
  180 minus that from vertical (body horizontal, e.g. on the floor), and the
  thighs, when seen, are at least ``LYING_MIN_THIGH_DEGREES`` from vertical. A
  child bending over has the head below the hips or vertical thighs, so it is
  never lying. It is a measured posture and takes precedence over the leg ratio,
  which means nothing for a horizontal body.
* a reason for every confirmed sample that is not measurable: no skeleton matched
  the child (``no_pose``), shoulders or hips hidden (``torso_hidden``), the body
  bent over with the shoulders down at hip height or lower (``bent_over``) or
  knees hidden (``knees_hidden``).
* a carried-over posture (``held``) while only the knees are hidden: sitting
  down or standing up moves the hips by about a thigh length, so as long as the
  hips stay within ``HOLD_MAX_HIP_SHIFT`` torso lengths of where they were when
  the posture was last measured (stable, ``min_stable_samples`` agreeing), the
  posture continues. A held posture is shown as such, never as a measurement,
  and never makes or confirms an event.
"""

import math


SHOULDERS, HIPS, KNEES = (5, 6), (11, 12), (13, 14)
LYING_MIN_DEGREES = 60.0
LYING_MIN_THIGH_DEGREES = 45.0
HOLD_MAX_HIP_SHIFT = 0.3
HOLD_MAX_IDENTITY_GAP = 1.0
KEYPOINT_CONFIDENCE = 0.5
MIN_TORSO = 0.02
STANDING_MIN_RATIO = 0.40
SITTING_MAX_RATIO = 0.25
MIN_STABLE_SAMPLES = 3
MAX_GAP_SECONDS = 3.0
POSTURE_STATES = ('standing', 'sitting', 'unclear', 'not_measurable')
POSTURE_STATES_V2 = ('standing', 'sitting', 'lying', 'unclear', 'not_measurable')
GAP_REASONS = ('no_pose', 'torso_hidden', 'bent_over', 'knees_hidden')
EVENT_KINDS = {('sitting', 'standing'): 'sit_to_stand', ('standing', 'sitting'): 'stand_to_sit'}
EVENT_KINDS_V2 = {**EVENT_KINDS,
                  ('sitting', 'lying'): 'to_lying', ('standing', 'lying'): 'to_lying',
                  ('lying', 'sitting'): 'from_lying', ('lying', 'standing'): 'from_lying'}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _mean_y(points, indices, minimum):
    visible = [points[index][1] for index in indices
               if points[index][2] >= minimum and _finite(points[index][1])]
    return sum(visible) / len(visible) if visible else None


def leg_ratio(points, *, keypoint_confidence=KEYPOINT_CONFIDENCE, standing_needs_both_knees=False,
              standing_min=STANDING_MIN_RATIO):
    """Return (knee y - hip y) / (hip y - shoulder y), or None when not measurable.

    With ``standing_needs_both_knees`` a ratio in the standing range counts only
    when both knees are confidently seen: a knee hidden by a table or an adult is
    often placed low by the pose model, which reads as standing. Such a reading is
    not measurable rather than a guess (sitting readings are unaffected).
    """
    if (not isinstance(points, list) or len(points) != 17
            or any(not isinstance(point, (list, tuple)) or len(point) < 3
                   or not all(_finite(value) for value in point[:3]) for point in points)):
        return None
    shoulder = _mean_y(points, SHOULDERS, keypoint_confidence)
    hip = _mean_y(points, HIPS, keypoint_confidence)
    knee = _mean_y(points, KNEES, keypoint_confidence)
    if shoulder is None or hip is None or knee is None or hip - shoulder < MIN_TORSO:
        return None
    ratio = (knee - hip) / (hip - shoulder)
    if (standing_needs_both_knees and ratio >= standing_min
            and sum(points[index][2] >= keypoint_confidence for index in KNEES) < len(KNEES)):
        return None
    return ratio


def _valid_points(points):
    return (isinstance(points, list) and len(points) == 17
            and all(isinstance(point, (list, tuple)) and len(point) >= 3
                    and all(_finite(value) for value in point[:3]) for point in points))


def _mean_xy(points, indices, minimum, aspect):
    visible = [points[index] for index in indices if points[index][2] >= minimum]
    if not visible:
        return None
    return (sum(point[0] for point in visible) / len(visible) * aspect,
            sum(point[1] for point in visible) / len(visible))


def _angle_from_vertical(start, end):
    """Degrees between the downward vertical and ``start -> end``: 0 down, 90 level, 180 up."""
    return math.degrees(math.atan2(abs(end[0] - start[0]), end[1] - start[1]))


def body_measures(points, *, aspect, keypoint_confidence=KEYPOINT_CONFIDENCE):
    """Return (torso angle, thigh angle, hip y, torso length); Nones when not measurable.

    Lengths are in frame-height units (x scaled by ``aspect`` = width / height), so
    angles are true image angles from vertical: 0 upright, 90 horizontal, above 90
    upside down. The thigh angle (hips to knees) is None when no knee is seen.
    """
    if not _finite(aspect) or aspect <= 0:
        raise ValueError('invalid_aspect')
    if not _valid_points(points):
        return None, None, None, None
    shoulder = _mean_xy(points, SHOULDERS, keypoint_confidence, aspect)
    hip = _mean_xy(points, HIPS, keypoint_confidence, aspect)
    if shoulder is None or hip is None:
        return None, None, None, None
    torso = math.hypot(hip[0] - shoulder[0], hip[1] - shoulder[1])
    if torso < MIN_TORSO:
        return None, None, None, None
    knee = _mean_xy(points, KNEES, keypoint_confidence, aspect)
    thigh = None if knee is None or math.dist(hip, knee) < MIN_TORSO else _angle_from_vertical(hip, knee)
    return _angle_from_vertical(shoulder, hip), thigh, hip[1], torso


def gap_reason(points, *, keypoint_confidence=KEYPOINT_CONFIDENCE):
    """Why a confirmed sample has no posture: ``no_pose``, ``torso_hidden`` or ``knees_hidden``."""
    if not _valid_points(points):
        return 'no_pose'
    shoulder = _mean_y(points, SHOULDERS, keypoint_confidence)
    hip = _mean_y(points, HIPS, keypoint_confidence)
    if shoulder is None or hip is None:
        return 'torso_hidden'
    if hip - shoulder < MIN_TORSO:
        return 'bent_over'
    return 'knees_hidden'


def classify_posture_v2(ratio, torso_angle, thigh_angle, *, standing_min=STANDING_MIN_RATIO,
                        sitting_max=SITTING_MAX_RATIO, lying_min=LYING_MIN_DEGREES,
                        lying_min_thigh=LYING_MIN_THIGH_DEGREES):
    """Version 2 state: ``lying`` for a horizontal body, otherwise the leg-ratio state."""
    if (not _finite(lying_min) or not 0 < lying_min < 90
            or not _finite(lying_min_thigh) or not 0 <= lying_min_thigh < 90):
        raise ValueError('invalid_posture_thresholds')
    if (torso_angle is not None and lying_min <= torso_angle <= 180 - lying_min
            and (thigh_angle is None or thigh_angle >= lying_min_thigh)):
        return 'lying'
    return classify_posture(ratio, standing_min=standing_min, sitting_max=sitting_max)


def held_postures(samples, *, min_stable_samples=MIN_STABLE_SAMPLES, max_hip_shift=HOLD_MAX_HIP_SHIFT,
                  max_identity_gap=HOLD_MAX_IDENTITY_GAP):
    """Per sample, the posture carried over while only the knees are hidden, else None.

    ``samples`` are time-ordered ``{'time', 'identity', 'state', 'reason', 'hip_y', 'torso'}``.
    The anchor is set once ``min_stable_samples`` consecutive measured sitting /
    standing samples agree (with hips seen); a different measured posture, lying or
    an identity gap longer than ``max_identity_gap`` seconds drops it (a shorter
    blip keeps it: the hip check below still has to pass). A sample is held only
    when its knees are hidden and its hips are within ``max_hip_shift`` anchor
    torso lengths of the anchor; hips outside it are not held but keep the anchor,
    so a child who rises and settles back at the same height is held again.
    """
    if (type(min_stable_samples) is not int or not 2 <= min_stable_samples <= 20
            or not _finite(max_hip_shift) or not 0 < max_hip_shift <= 2
            or not _finite(max_identity_gap) or not 0 <= max_identity_gap <= 10):
        raise ValueError('invalid_posture_parameters')
    held = []
    anchor = run_state = last_confirmed = None
    run = 0
    for sample in samples:
        state = sample['state']
        if sample['identity'] != 'confirmed':
            held.append(None)
            continue
        if (state == 'lying' or last_confirmed is None
                or sample['time'] - last_confirmed > max_identity_gap + 1e-9):
            anchor = run_state = None
            run = 0
        last_confirmed = sample['time']
        if state == 'lying':
            held.append(None)
            continue
        hip, torso = sample['hip_y'], sample['torso']
        if state in ('sitting', 'standing'):
            run = run + 1 if state == run_state else 1
            run_state = state
            if run >= min_stable_samples and hip is not None:
                anchor = (state, hip, torso)
            elif anchor is not None and anchor[0] != state:
                anchor = None
            held.append(None)
            continue
        carried = None
        if (anchor is not None and hip is not None and sample['reason'] == 'knees_hidden'
                and abs(hip - anchor[1]) <= max_hip_shift * anchor[2]):
            carried = anchor[0]
        held.append(carried)
    return held


def classify_posture(ratio, *, standing_min=STANDING_MIN_RATIO, sitting_max=SITTING_MAX_RATIO):
    """Map a leg ratio to standing / sitting / unclear / not_measurable."""
    if not _finite(standing_min) or not _finite(sitting_max) or sitting_max >= standing_min:
        raise ValueError('invalid_posture_thresholds')
    if ratio is None:
        return 'not_measurable'
    if ratio >= standing_min:
        return 'standing'
    if ratio <= sitting_max:
        return 'sitting'
    return 'unclear'


def posture_events(samples, *, min_stable_samples=MIN_STABLE_SAMPLES,
                   max_gap_seconds=MAX_GAP_SECONDS, kinds=EVENT_KINDS):
    """Transitions between stable postures inside continuous confirmed identity.

    ``samples`` are time-ordered ``{'time', 'identity', 'state'}``. A posture is
    stable after ``min_stable_samples`` consecutive measured samples agree;
    unclear / not_measurable samples neither confirm nor break that count. An
    identity gap or more than ``max_gap_seconds`` without a measured posture
    forgets the stable posture, so no event is inferred across it. Each event
    cites the last frame of the old posture and the first frame of the new one;
    ``detected_time`` is the sample that confirmed it, the earliest moment a
    causal (replay or live) display may show the event. ``kinds`` names the
    transitions; its states are the measured ones (version 2 adds ``lying``).
    """
    measured = {state for pair in kinds for state in pair}
    if (type(min_stable_samples) is not int or not 2 <= min_stable_samples <= 20
            or not _finite(max_gap_seconds) or not 0 < max_gap_seconds <= 60):
        raise ValueError('invalid_posture_parameters')
    events = []
    stable = stable_last_time = None
    candidate = candidate_first_time = None
    candidate_count = 0
    last_measured_time = None
    for sample in samples:
        if sample['identity'] != 'confirmed':
            stable = candidate = last_measured_time = None
            continue
        state = sample['state']
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
