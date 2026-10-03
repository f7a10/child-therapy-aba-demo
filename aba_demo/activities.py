"""Therapist-set session activities: the only three, and their segment tiling.

Activities are set by the therapist only; nothing in the system infers or
changes them. Segments must tile the decoded session exactly.
"""

import math


ACTIVITIES = ('table', 'movement', 'break')
SEGMENT_KEYS = frozenset({'start_time', 'end_time', 'activity'})


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate_segments(segments, session_end):
    if (not isinstance(segments, list) or not segments
            or any(not isinstance(segment, dict) or set(segment) != SEGMENT_KEYS
                   or segment['activity'] not in ACTIVITIES
                   or not _finite(segment['start_time']) or not _finite(segment['end_time'])
                   or segment['start_time'] >= segment['end_time'] for segment in segments)
            or segments[0]['start_time'] != 0
            or segments[-1]['end_time'] != session_end
            or any(current['start_time'] != previous['end_time']
                   for previous, current in zip(segments, segments[1:]))):
        raise ValueError('invalid_activity_segments')


def activity_at(segments, time):
    """Therapist-set activity covering ``time`` (the last segment includes its end)."""
    for segment in segments:
        if segment['start_time'] <= time < segment['end_time']:
            return segment['activity']
    return segments[-1]['activity']
