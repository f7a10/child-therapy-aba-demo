"""Unified session timeline: measured channel events placed in therapist-set activities.

Activities are set by the therapist only (table / movement / break); nothing here
infers or changes them. Every measured event stays on the timeline; the provisional
rules only decide whether it is raised as a ``flag`` for review or shown as
``info``. Changing an activity re-derives levels without re-analysing video. The
timeline is derived data: ``verify_timeline`` rebuilds it from its bound channels.
Channels arrive through the unified event format in ``channel_events``.
"""

import copy
import json
import math

from .activities import ACTIVITIES, SEGMENT_KEYS, _validate_segments, activity_at  # noqa: F401
from .channel_events import CHANNELS, channel_reading
from .grouping import group_by_time


RULES_VERSION = 'provisional-1'
# (activity, channel, kind) -> level; anything not listed is 'info'.
FLAG_RULES = frozenset({('table', 'posture', 'sit_to_stand')})
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def level_for(activity, channel, kind):
    return 'flag' if (activity, channel, kind) in FLAG_RULES else 'info'


def _readings(channels, source_duration):
    """Validate every bound channel; all must describe the same video and tracking."""
    if (not isinstance(channels, dict) or not channels
            or any(name not in CHANNELS or not isinstance(bound, tuple) or len(bound) != 2
                   or not isinstance(bound[1], str) or len(bound[1]) != 64
                   or not set(bound[1]) <= _SHA_CHARACTERS
                   for name, bound in channels.items())):
        raise ValueError('invalid_channels')
    readings = {name: channel_reading(name, document, source_duration)
                for name, (document, _) in sorted(channels.items())}
    bindings = {(reading['source_sha256'], reading['tracking_candidate_sha256'],
                 reading['decoded_seconds']) for reading in readings.values()}
    if len(bindings) != 1:
        raise ValueError('invalid_channels')
    return readings, bindings.pop()


def build_timeline(channels, activity_segments, source_duration):
    """Return the timeline for ``channels`` = {name: (document, document_sha256)}."""
    readings, (source_sha256, tracking_sha256, decoded_seconds) = _readings(
        channels, source_duration)
    _validate_segments(activity_segments, decoded_seconds)
    entries = []
    for name, reading in readings.items():
        for event in reading['events']:
            activity = activity_at(activity_segments, event['end_time'])
            entries.append({
                'entry_id': f'tl-{name}-' + event['event_id'], 'channel': name,
                'source_event_id': event['event_id'], 'kind': event['kind'],
                'origin': event['origin'],
                'start_time': event['start_time'], 'end_time': event['end_time'],
                'detected_time': event['detected_time'],
                'evidence_times': event['evidence_times'], 'activity': activity,
                'level': level_for(activity, name, event['kind']),
                'clinician_confirmation': event['clinician_confirmation'],
                'details': event['details'],
            })
    entries.sort(key=lambda entry: (entry['start_time'], entry['entry_id']))
    # Entries that happen together become one reviewable moment (one strip line).
    groups = [{'group_id': f'grp-{number:06d}',
               'start_time': min(e['start_time'] for e in group),
               'end_time': max(e['end_time'] for e in group),
               'detected_time': max(e['detected_time'] for e in group),
               'entry_ids': [e['entry_id'] for e in group],
               'level': 'flag' if any(e['level'] == 'flag' for e in group) else 'info'}
              for number, group in enumerate(group_by_time(entries, key='entry_id'))]
    return {'schema_version': 3, 'kind': 'session_timeline',
            'source_sha256': source_sha256, 'tracking_candidate_sha256': tracking_sha256,
            'channels': {name: sha for name, (_, sha) in sorted(channels.items())},
            'rules_version': RULES_VERSION,
            'activity_segments': copy.deepcopy(activity_segments), 'entries': entries,
            'groups': groups}


def verify_timeline(timeline, channels, source_duration):
    """True only if ``timeline`` equals a rebuild from its exact bound channels."""
    try:
        rebuilt = build_timeline(channels, timeline['activity_segments'], source_duration)
    except (ValueError, TypeError, KeyError):
        raise ValueError('invalid_session_timeline') from None
    if timeline != rebuilt:
        raise ValueError('invalid_session_timeline')
    return True


def encode_timeline(timeline):
    return json.dumps(timeline, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
