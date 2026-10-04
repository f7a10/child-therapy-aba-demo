"""Pure posture features from the selected child's own pose keypoints.

The leg ratio is the vertical drop of the knees below the hips divided by the
torso length (shoulders to hips) in image coordinates. Thresholds are
provisional, measured on two development recordings only, and there is a gray
band between them where the state is ``unclear``: the reader never guesses.
Missing joints are ``not_measurable``, never a posture.
"""

import math


SHOULDERS, HIPS, KNEES = (5, 6), (11, 12), (13, 14)
KEYPOINT_CONFIDENCE = 0.5
MIN_TORSO = 0.02
STANDING_MIN_RATIO = 0.40
SITTING_MAX_RATIO = 0.25
MIN_STABLE_SAMPLES = 3
MAX_GAP_SECONDS = 3.0
POSTURE_STATES = ('standing', 'sitting', 'unclear', 'not_measurable')
EVENT_KINDS = {('sitting', 'standing'): 'sit_to_stand', ('standing', 'sitting'): 'stand_to_sit'}


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
                   max_gap_seconds=MAX_GAP_SECONDS):
    """Transitions between stable postures inside continuous confirmed identity.

    ``samples`` are time-ordered ``{'time', 'identity', 'state'}``. A posture is
    stable after ``min_stable_samples`` consecutive measured samples agree;
    unclear / not_measurable samples neither confirm nor break that count. An
    identity gap or more than ``max_gap_seconds`` without a measured posture
    forgets the stable posture, so no event is inferred across it. Each event
    cites the last frame of the old posture and the first frame of the new one;
    ``detected_time`` is the sample that confirmed it, the earliest moment a
    causal (replay or live) display may show the event.
    """
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
        if state not in ('standing', 'sitting'):
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
                events.append({'kind': EVENT_KINDS[(stable, candidate)],
                               'start_time': stable_last_time, 'end_time': candidate_first_time,
                               'evidence_times': [stable_last_time, candidate_first_time],
                               'detected_time': time})
            stable, stable_last_time, candidate = candidate, time, None
    return events
