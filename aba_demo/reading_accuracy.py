"""How well the readings match what a person saw: labels, doctor verdicts, recording hints.

Derived data only. A reviewer labels the child every few seconds (posture and,
when a work area was drawn, whether the child is at it, or "not visible"). Each
label is compared with the reading nearest that moment:

* ``measured`` readings and ``inferred`` (held) readings are scored separately,
  so the inferred posture has its own accuracy;
* a visible child with no reading counts as ``missed`` (coverage);
* a reading while the reviewer could not see the child is ``unverifiable``.

Doctor verdicts on moments (confirmed / not seen / unsure) give the share of
detected moments that really happened, per measured kind. Recording hints turn
the gap reasons of a session into concrete advice for the next recording.
"""

from .session_measures import _at, area_series, posture_series

LABEL_INTERVAL = 5.0
POSTURE_LABELS = ('sitting', 'standing', 'lying', 'not_visible')
AREA_LABELS = ('at_area', 'away_from_area', 'not_visible')
# Gap reason -> (share of the session above which a hint is given, hint code).
HINTS = (('posture', 'knees_hidden', 0.20, 'knees_hidden'),
         ('posture', 'torso_hidden', 0.10, 'body_hidden'),
         ('posture', 'identity', 0.15, 'child_lost'),
         ('orientation', 'camera', 0.10, 'camera_moving'))


def label_points(decoded, interval=LABEL_INTERVAL):
    """Times to label: every ``interval`` seconds after the start, within the session."""
    points, time = [], interval
    while time <= decoded + 1e-9:
        points.append(round(time, 1))
        time += interval
    return points


def _empty():
    return {'labeled': 0, 'not_visible': 0, 'missed': 0, 'unverifiable': 0,
            'measured': {'count': 0, 'correct': 0}, 'inferred': {'count': 0, 'correct': 0},
            'confusion': {}}


def _score(result, label, reading):
    """Add one labeled point; ``reading`` is (state, inferred) or None."""
    if label == 'not_visible':
        result['not_visible'] += 1
        if reading is not None:
            result['unverifiable'] += 1
        return
    result['labeled'] += 1
    if reading is None:
        result['missed'] += 1
        return
    state, inferred = reading
    bucket = result['inferred' if inferred else 'measured']
    bucket['count'] += 1
    bucket['correct'] += state == label
    row = result['confusion'].setdefault(label, {})
    row[state] = row.get(state, 0) + 1


def label_accuracy(labels, documents):
    """Per channel scores of the readings against ``labels`` ({time: {'posture', 'area'}})."""
    posture = posture_series(documents['posture']) if 'posture' in documents else []
    area = area_series(documents['orientation']) if 'orientation' in documents else []
    scores = {}
    for channel, series, key in (('posture', posture, 'posture'), ('area', area, 'area')):
        if not series:
            continue
        result = _empty()
        for time, label in sorted(labels.items()):
            value = label.get(key)
            if value is None:
                continue
            row = _at(series, float(time))
            reading = None
            if row is not None and row[1] is not None:
                reading = (row[1], bool(row[2]) if len(row) > 2 else False)
            _score(result, value, reading)
        scores[channel] = result
    return scores


def merge_scores(total, scores):
    """Add one session's ``label_accuracy`` into a running total (in place)."""
    for channel, result in scores.items():
        into = total.setdefault(channel, _empty())
        for key in ('labeled', 'not_visible', 'missed', 'unverifiable'):
            into[key] += result[key]
        for key in ('measured', 'inferred'):
            for field in ('count', 'correct'):
                into[key][field] += result[key][field]
        for label, row in result['confusion'].items():
            target = into['confusion'].setdefault(label, {})
            for state, count in row.items():
                target[state] = target.get(state, 0) + count
    return total


def verdict_counts(entries, groups, marks):
    """Doctor verdicts per measured kind (``channel:kind``) over the marked moments."""
    by_id = {entry['entry_id']: entry for entry in entries}
    counts = {}
    for group in groups:
        mark = marks.get(group['entry_ids'][0])
        if mark is None:
            continue
        kinds = {f"{by_id[i]['channel']}:{by_id[i]['kind']}" for i in group['entry_ids']
                 if i in by_id and by_id[i]['origin'] == 'measured'}
        for kind in kinds:
            row = counts.setdefault(kind, {'confirmed': 0, 'not_seen': 0, 'unsure': 0})
            row[mark['verdict']] += 1
    return counts


def recording_hints(summaries):
    """Advice codes for the next recording from this session's gap reasons."""
    hints = []
    for channel, reason, limit, code in HINTS:
        share = (summaries.get(channel) or {}).get('reasons', {}).get(reason, 0.0)
        if share >= limit and code not in hints:
            hints.append(code)
    return hints
