"""Group events that happen together into one reviewable moment.

Events are ordered by start time; an event joins the current group when it starts
no later than ``gap`` seconds after the group's latest end. One rule serves the
timeline (one line per moment) and the context channel (one question per moment).
The dashboard mirrors it in JavaScript; a test keeps the two equal.
"""

import math


GROUP_GAP_SECONDS = 1.0


def group_by_time(items, gap=GROUP_GAP_SECONDS, key=None):
    """Return lists of ``items`` (dicts with start_time / end_time), in time order.

    ``key`` names a field used to break start-time ties deterministically.
    """
    if type(gap) not in (int, float) or not math.isfinite(gap) or gap < 0:
        raise ValueError('invalid_group_gap')
    ordered = sorted(items, key=lambda i: (i['start_time'], '' if key is None else i[key]))
    groups, group_end = [], None
    for item in ordered:
        if groups and item['start_time'] <= group_end + gap + 1e-9:
            groups[-1].append(item)
            group_end = max(group_end, item['end_time'])
        else:
            groups.append([item])
            group_end = item['end_time']
    return groups
