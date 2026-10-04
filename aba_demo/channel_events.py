"""Unified channel event: the one shape every observation channel hands to the timeline.

Each channel keeps its own strict document and validation (posture recomputes
its events from samples, for example); an adapter turns a validated document
into channel events. The timeline only ever sees these events, so adding a
channel means registering its kinds, origin and adapter here.

``origin`` is ``measured`` for local measurement and ``suggested`` for model
readings (the context channel), which are never more than a suggestion.
``detected_time`` is the earliest moment a causal display may show the event.
``details`` holds a suggested channel's closed-enum observations (short snake_case
keys and values only, never free text); measured channels leave it empty.
"""

import copy
import math
import re

from .context_channel_schema import validate_context_channel_document
from .context_v2 import DOCUMENT_KIND as CONTEXT_V2_KIND, validate_context_v2_document
from .large_movement_schema import validate_large_movement_document
from .orientation_schema import validate_orientation_document
from .posture_schema import CLINICIAN_CONFIRMATIONS, validate_posture_document


EVENT_KEYS = frozenset({'event_id', 'channel', 'kind', 'origin', 'start_time', 'end_time',
                        'detected_time', 'evidence_times', 'clinician_confirmation',
                        'details'})
ORIGINS = ('measured', 'suggested')
MAX_EVIDENCE_TIMES = 8
MAX_DETAILS = 8
_TOKEN = re.compile(r'[a-z][a-z_]{0,39}')


def _measured_events(channel):
    """Adapter for channels whose own events already carry the shared event fields."""
    def to_events(document):
        return [{'event_id': event['event_id'], 'channel': channel, 'kind': event['kind'],
                 'origin': 'measured', 'start_time': event['start_time'],
                 'end_time': event['end_time'], 'detected_time': event['detected_time'],
                 'evidence_times': list(event['evidence_times']),
                 'clinician_confirmation': event['clinician_confirmation'],
                 'details': {}}
                for event in document['events']]
    return to_events


def _context_events(document):
    return [{'event_id': event['event_id'], 'channel': 'context', 'kind': event['kind'],
             'origin': 'suggested', 'start_time': event['start_time'],
             'end_time': event['end_time'], 'detected_time': event['detected_time'],
             'evidence_times': list(event['evidence_times']),
             'clinician_confirmation': event['clinician_confirmation'],
             'details': dict(event['details'])}
            for event in document['events']]


def _validate_context(document, source_duration):
    """Both context readings: v2 (before / during / after) and the original v1."""
    if isinstance(document, dict) and document.get('kind') == CONTEXT_V2_KIND:
        return validate_context_v2_document(document, source_duration)
    return validate_context_channel_document(document, source_duration)


# channel -> (allowed kinds, origin, validate(document, duration), to_events(document))
CHANNELS = {
    'posture': (('sit_to_stand', 'stand_to_sit'), 'measured',
                validate_posture_document, _measured_events('posture')),
    'orientation': (('turned_away_from_task', 'turned_back_to_task'), 'measured',
                    validate_orientation_document, _measured_events('orientation')),
    'movement': (('large_movement',), 'measured',
                 validate_large_movement_document, _measured_events('movement')),
    'context': (('context_note',), 'suggested',
                _validate_context, _context_events),
}

# Document ``kind`` written by each channel's reader -> channel name.
DOCUMENT_KINDS = {'posture_reading': 'posture', 'orientation_reading': 'orientation',
                  'large_movement_reading': 'movement',
                  'context_channel_reading': 'context', CONTEXT_V2_KIND: 'context'}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _valid_details(details, origin):
    return (isinstance(details, dict) and len(details) <= MAX_DETAILS
            and (origin == 'suggested' or not details)
            and all(isinstance(key, str) and _TOKEN.fullmatch(key)
                    and isinstance(value, str) and _TOKEN.fullmatch(value)
                    for key, value in details.items()))


def _valid_event(event, decoded_seconds):
    if (not isinstance(event, dict) or set(event) != EVENT_KEYS
            or event['channel'] not in CHANNELS):
        return False
    kinds, origin, _, _ = CHANNELS[event['channel']]
    evidence = event['evidence_times']
    times = (event['start_time'], event['end_time'], event['detected_time'])
    return (isinstance(event['event_id'], str) and 1 <= len(event['event_id']) <= 64
            and event['kind'] in kinds and event['origin'] == origin
            and all(_finite(time) for time in times)
            and 0 <= event['start_time'] <= event['end_time']
            <= event['detected_time'] <= decoded_seconds
            and isinstance(evidence, list) and 1 <= len(evidence) <= MAX_EVIDENCE_TIMES
            and all(_finite(time) for time in evidence)
            and all(earlier <= later for earlier, later in zip(evidence, evidence[1:]))
            and event['start_time'] <= evidence[0] and evidence[-1] <= event['end_time']
            and event['clinician_confirmation'] in CLINICIAN_CONFIRMATIONS
            and _valid_details(event['details'], origin))


def validate_channel_events(events, decoded_seconds):
    """Return a copy of ``events``; raise ValueError('invalid_channel_events')."""
    try:
        if (not isinstance(events, list)
                or not all(_valid_event(event, decoded_seconds) for event in events)
                or len({event['event_id'] for event in events}) != len(events)
                or any(current['start_time'] < previous['start_time']
                       for previous, current in zip(events, events[1:]))):
            raise ValueError
    except (TypeError, KeyError, ValueError):
        raise ValueError('invalid_channel_events') from None
    return copy.deepcopy(events)


def channel_reading(channel, document, source_duration):
    """Validate one channel document and return its binding and unified events."""
    if channel not in CHANNELS:
        raise ValueError('unknown_channel')
    _, _, validate, to_events = CHANNELS[channel]
    validated = copy.deepcopy(validate(document, source_duration))
    return {'source_sha256': validated['source_sha256'],
            'tracking_candidate_sha256': validated['tracking_candidate_sha256'],
            'decoded_seconds': validated['decoded_seconds'],
            'events': validate_channel_events(to_events(validated),
                                              validated['decoded_seconds'])}


def reading_for_document(document, source_duration):
    """Like ``channel_reading`` with the channel found from the document ``kind``."""
    kind = document.get('kind') if isinstance(document, dict) else None
    if not isinstance(kind, str) or kind not in DOCUMENT_KINDS:
        raise ValueError('unknown_channel')
    channel = DOCUMENT_KINDS[kind]
    return {'channel': channel, **channel_reading(channel, document, source_duration)}
