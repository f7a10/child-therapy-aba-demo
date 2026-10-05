"""Session measures in the language of ABA data sheets, from the channel documents.

Derived data only: nothing here reads video or changes a channel document. From
the per-sample states it builds

* episodes: stretches the child was standing, lying or away from the work area,
  with their start, end and duration (``min_seconds`` or longer). A short
  unmeasured stretch (``bridge_seconds`` or less) between two samples in the same
  state does not split an episode; a longer one does. Whether the episode's start
  and end were actually seen is kept, so a cut episode is never shown as complete.
* a summary: share of the measured posture time spent sitting, episode counts,
  total and longest durations, large movements, and how much of the session each
  measure could see.
* an interval sheet: every ``interval_seconds`` the state at that moment
  (momentary time sampling) and whether something happened during the interval
  (partial interval), with ``None`` where nothing was measured.

Inferred (held) posture counts as posture time and is marked; unmeasured time is
never counted as sitting or as anything else.
"""

import bisect
import math

from .large_movement_features import motion_states

MIN_EPISODE_SECONDS = 1.0
BRIDGE_SECONDS = 2.0
INTERVAL_SECONDS = 10.0
SAMPLE_TOLERANCE = 0.3
EPISODE_KINDS = ('standing', 'lying', 'away_from_area')
POSTURES = ('sitting', 'standing', 'lying')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def posture_series(document):
    """Per sample (time, posture, inferred) from a posture reading; posture None if unknown."""
    series = []
    for sample in document.get('samples', []):
        state = sample.get('state')
        if state in POSTURES:
            series.append((sample['time'], state, False))
        elif sample.get('held') in POSTURES:
            series.append((sample['time'], sample['held'], True))
        else:
            series.append((sample['time'], None, False))
    return series


def area_series(document):
    """Per sample (time, at_area / away_from_area / None) from a work-area reading."""
    return [(sample['time'], sample.get('area_state') if sample.get('area_state') in
             ('at_area', 'away_from_area') else None) for sample in document.get('samples', [])]


def motion_series(document):
    """Per sample (time, moving / still / None) from a large-movement reading."""
    samples = document.get('samples', [])
    if not samples or 'centre' not in samples[0]:
        return []
    return [(sample['time'], state) for sample, state in zip(samples, motion_states(samples))]


def _bridged(states, times, bridge_seconds):
    """States with short unknown stretches between two equal states filled in."""
    filled = list(states)
    index = 0
    while index < len(filled):
        if filled[index] is not None:
            index += 1
            continue
        end = index
        while end < len(filled) and filled[end] is None:
            end += 1
        if 0 < index and end < len(filled) and filled[index - 1] == filled[end] \
                and times[end] - times[index - 1] <= bridge_seconds + 1e-9:
            for fill in range(index, end):
                filled[fill] = filled[index - 1]
        index = end
    return filled


def episodes(series, kinds, *, decoded, min_seconds=MIN_EPISODE_SECONDS, bridge_seconds=BRIDGE_SECONDS):
    """Episodes of each state in ``kinds`` from a (time, state, ...) series, in time order."""
    if not series:
        return []
    times = [row[0] for row in series]
    states = _bridged([row[1] for row in series], times, bridge_seconds)
    found = []
    index = 0
    while index < len(states):
        state = states[index]
        end = index
        while end < len(states) and states[end] == state:
            end += 1
        if state in kinds:
            start_time = times[index]
            end_time = times[end] if end < len(times) else decoded
            if end_time - start_time >= min_seconds - 1e-9:
                found.append({'kind': state, 'start': start_time, 'end': end_time,
                              'duration': end_time - start_time,
                              'start_seen': index > 0 and states[index - 1] is not None,
                              'end_seen': end < len(states) and states[end] is not None})
        index = end
    return found


def _durations(series, decoded):
    """Seconds spent in each state (unknown under None) from a (time, state, ...) series."""
    totals = {}
    for index, row in enumerate(series):
        stop = series[index + 1][0] if index + 1 < len(series) else decoded
        totals[row[1]] = totals.get(row[1], 0.0) + max(0.0, stop - row[0])
    return totals


def _stats(found, kind):
    mine = [episode['duration'] for episode in found if episode['kind'] == kind]
    return {'count': len(mine), 'total': sum(mine), 'longest': max(mine, default=0.0)}


def _at(series, time):
    """The sample nearest ``time`` (within the tolerance), else None."""
    times = [row[0] for row in series]
    index = bisect.bisect_left(times, time)
    near = [row for row in series[max(0, index - 1):index + 1] if abs(row[0] - time) <= SAMPLE_TOLERANCE + 1e-9]
    return min(near, key=lambda row: abs(row[0] - time), default=None)


def _during(series, start, end, hit):
    """True if any sample in (start, end] is ``hit``; False if all seen and none is; None if mostly unseen."""
    times = [row[0] for row in series]
    inside = series[bisect.bisect_right(times, start):bisect.bisect_right(times, end + 1e-9)]
    seen = [row for row in inside if row[1] is not None]
    if any(hit(row[1]) for row in seen):
        return True
    return False if inside and len(seen) >= len(inside) / 2 else None


def interval_sheet(posture, area, motion, movement_events, *, decoded, interval_seconds=INTERVAL_SECONDS):
    """One row per interval: the state at its end, and what happened during it."""
    rows = []
    end = interval_seconds
    while end <= decoded + 1e-9 or not rows:
        end = min(end, decoded)
        start = max(0.0, end - interval_seconds)
        at_posture = _at(posture, end)
        at_area = _at(area, end)
        at_motion = _at(motion, end)
        rows.append({
            'start': start, 'end': end,
            'posture': at_posture[1] if at_posture else None,
            'posture_inferred': bool(at_posture and at_posture[2]),
            'area': at_area[1] if at_area else None,
            'motion': at_motion[1] if at_motion else None,
            'out_of_seat': _during(posture, start, end, lambda state: state in ('standing', 'lying')) if posture else None,
            'away_from_area': _during(area, start, end, lambda state: state == 'away_from_area') if area else None,
            'large_movement': (any(start < event['start_time'] <= end or start < event['end_time'] <= end
                                   or (event['start_time'] <= start and end <= event['end_time'])
                                   for event in movement_events) if motion else None),
        })
        if end >= decoded:
            break
        end += interval_seconds
    return rows


def session_measures(documents, decoded, *, interval_seconds=INTERVAL_SECONDS):
    """Episodes, summary and interval sheet for one session; ``documents`` by channel name."""
    if not _finite(decoded) or decoded <= 0:
        raise ValueError('invalid_decoded_seconds')
    posture = posture_series(documents['posture']) if 'posture' in documents else []
    area = area_series(documents['orientation']) if 'orientation' in documents else []
    motion = motion_series(documents['movement']) if 'movement' in documents else []
    movement_events = documents['movement'].get('events', []) if 'movement' in documents else []
    if not any(row[1] for row in area):
        area = []
    found = sorted(episodes(posture, ('standing', 'lying'), decoded=decoded)
                   + episodes(area, ('away_from_area',), decoded=decoded),
                   key=lambda episode: (episode['start'], episode['kind']))
    summary = {'episodes': {kind: _stats(found, kind) for kind in EPISODE_KINDS},
               'large_movements': len(movement_events) if 'movement' in documents else None}
    if posture:
        totals = _durations(posture, decoded)
        known = sum(seconds for state, seconds in totals.items() if state is not None)
        inferred = sum(max(0.0, (posture[i + 1][0] if i + 1 < len(posture) else decoded) - row[0])
                       for i, row in enumerate(posture) if row[2])
        summary['posture'] = {'measured_share': known / decoded, 'inferred_share': inferred / decoded,
                              **{f'{state}_share': (totals.get(state, 0.0) / known if known else None)
                                 for state in POSTURES}}
    if area:
        totals = _durations(area, decoded)
        known = totals.get('at_area', 0.0) + totals.get('away_from_area', 0.0)
        summary['area'] = {'measured_share': known / decoded,
                           'at_area_share': totals.get('at_area', 0.0) / known if known else None}
    if motion:
        totals = _durations(motion, decoded)
        known = totals.get('moving', 0.0) + totals.get('still', 0.0)
        summary['motion'] = {'measured_share': known / decoded,
                             'moving_share': totals.get('moving', 0.0) / known if known else None}
    return {'episodes': found, 'summary': summary,
            'intervals': interval_sheet(posture, area, motion, movement_events, decoded=decoded,
                                        interval_seconds=interval_seconds),
            'interval_seconds': interval_seconds}


CSV_COLUMNS = ('interval_start', 'interval_end', 'posture_at_end', 'posture_inferred', 'work_area_at_end',
               'motion_at_end', 'out_of_seat_during', 'away_from_area_during', 'large_movement_during')


def _clock(seconds):
    whole = int(round(seconds))
    return f'{whole // 60}:{whole % 60:02d}'


def _cell(value):
    if value is None:
        return 'not_measured'
    if value is True:
        return 'yes'
    if value is False:
        return 'no'
    return str(value)


def intervals_csv(measures):
    """The interval sheet as CSV text (one header row, one row per interval)."""
    lines = [','.join(CSV_COLUMNS)]
    for row in measures['intervals']:
        lines.append(','.join([_clock(row['start']), _clock(row['end']), _cell(row['posture']),
                               _cell(row['posture_inferred'] if row['posture'] else None),
                               _cell(row['area']), _cell(row['motion']), _cell(row['out_of_seat']),
                               _cell(row['away_from_area']), _cell(row['large_movement'])]))
    return '\r\n'.join(lines) + '\r\n'


def episodes_csv(measures):
    """The episodes as CSV text."""
    lines = ['kind,start,end,duration_seconds,start_seen,end_seen']
    for episode in measures['episodes']:
        lines.append(','.join([episode['kind'], _clock(episode['start']), _clock(episode['end']),
                               f"{episode['duration']:.1f}", _cell(episode['start_seen']),
                               _cell(episode['end_seen'])]))
    return '\r\n'.join(lines) + '\r\n'
