"""Context channel: closed-enum notes from a VLM on moments the local channels marked.

Only a few frames per moment are ever sent; local events that happen together
(``aba_demo.grouping``) form one moment and are asked about once. The question
set follows the therapist-set activity at the moment, so the model is asked only
what is meaningful there (table: where the child is and whether the child's own
hands hold the material; movement and break: where the child is). Adult hand
contact was tried and dropped: from these camera angles the model could not tell
contact from closeness.
There is no free text, no session-type suggestion, and nothing about attention,
emotion, intent or diagnosis. If the model cannot tell the child's body apart from
an adult's, every other answer must be ``not_observable``. The notes are
suggestions for the clinician: they never change a level or the therapist-set
segments. Validation recomputes each moment's activity and the notes.
"""

import copy
import hashlib
import json
import math
import re

from .activities import ACTIVITIES, _validate_segments, activity_at
from .openrouter_context import VisualTask


FIELD_VALUES = {
    'child_separable': ('yes', 'no'),
    'child_location': ('at_table', 'away_from_table', 'walking', 'on_floor', 'not_observable'),
    'child_handling_material': ('yes', 'no', 'ambiguous', 'not_observable'),
}
QUESTION_SETS = {
    'table': ('child_separable', 'child_location', 'child_handling_material'),
    'movement': ('child_separable', 'child_location'),
    'break': ('child_separable', 'child_location'),
}
_INTRO = """You see 2-4 frames from a recorded therapy session, in time order. In each scene
image the selected CHILD is outlined in green; other people are outlined in red. The second
image of each frame is an unannotated close-up of the child's area.
Answer only what is directly visible across the frames. Never describe feelings, attention,
intentions, reasons, behavior meaning or diagnosis.
"""
_QUESTIONS = {
    'child_separable': """child_separable: yes only if in every frame you can tell which body
parts are the green-outlined child's and which belong to the red-outlined people; otherwise no.
""",
    'child_location': """child_location: at_table if the child is at or seated at a table;
away_from_table if the child is upright and still, away from any table; walking if the child
is visibly stepping or moving across the room between frames; on_floor if the child is
sitting, lying or crawling on the floor; not_observable if it cannot be seen.
""",
    'child_handling_material': """child_handling_material: yes only if the child's own hand
visibly holds or manipulates a toy or task material; no if clearly not; ambiguous if unclear.
""",
}
_OUTRO = """If child_separable is no, every other field must be not_observable.
Use not_observable when the relevant part is hidden in the frames."""
PROMPTS = {activity: _INTRO + ''.join(_QUESTIONS[name] for name in fields) + _OUTRO
           for activity, fields in QUESTION_SETS.items()}
PROMPT_SHA256 = {activity: hashlib.sha256(prompt.encode('utf-8')).hexdigest()
                 for activity, prompt in PROMPTS.items()}
MIN_FRAMES, MAX_FRAMES = 2, 4
MAX_OUTPUT_CHARS = 2048
MAX_MOMENTS = 200
ANCHOR_CHANNELS = ('posture', 'movement', 'orientation')
EVENT_KIND = 'context_note'
CLINICIAN_CONFIRMATIONS = ('pending', 'confirmed', 'rejected')
DOCUMENT_KEYS = frozenset({'schema_version', 'kind', 'source_sha256',
                           'tracking_candidate_sha256', 'decoded_seconds', 'config',
                           'activity_segments', 'moments', 'events'})
CONFIG_KEYS = frozenset({'model', 'provider', 'prompt_sha256', 'max_frames_per_moment'})
MAX_ANCHORS = 8
MOMENT_KEYS = frozenset({'moment_id', 'anchors', 'start_time',
                         'end_time', 'detected_time', 'frame_times', 'activity', 'status',
                         'failure', 'observation'})
_CODE = re.compile(r'[a-z][a-z0-9_:]{0,79}')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}')
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _valid_observation(value, activity):
    fields = QUESTION_SETS[activity]
    return (isinstance(value, dict) and set(value) == set(fields)
            and all(value[name] in FIELD_VALUES[name] for name in fields)
            and (value['child_separable'] == 'yes'
                 or all(value[name] == 'not_observable' for name in fields
                        if name != 'child_separable')))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid_context:duplicate_key')
        result[key] = value
    return result


def _task(activity):
    fields = QUESTION_SETS[activity]

    def output_schema(frame_count):
        if type(frame_count) is not int or not MIN_FRAMES <= frame_count <= MAX_FRAMES:
            raise ValueError('invalid_context_window')
        return {'type': 'object', 'additionalProperties': False,
                'properties': {name: {'type': 'string', 'enum': list(FIELD_VALUES[name])}
                               for name in fields},
                'required': list(fields)}

    def parse(raw, times):
        """Return the validated observation; raise ValueError('invalid_context:<rule>')."""
        if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_OUTPUT_CHARS:
            raise ValueError('invalid_context:size')
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except ValueError as error:
            if str(error).startswith('invalid_context'):
                raise
            raise ValueError('invalid_context:json') from None
        if not isinstance(value, dict) or set(value) != set(fields):
            raise ValueError('invalid_context:keys')
        if not all(value[name] in FIELD_VALUES[name] for name in fields):
            raise ValueError('invalid_context:enum')
        if not _valid_observation(value, activity):
            raise ValueError('invalid_context:separable')
        return value

    return VisualTask(name='aba_moment_context_' + activity, prompt=PROMPTS[activity],
                      output_schema=output_schema, parse=parse)


CONTEXT_TASKS = {activity: _task(activity) for activity in ACTIVITIES}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA_CHARACTERS


def _valid_moment(moment, decoded, segments):
    if not isinstance(moment, dict) or set(moment) != MOMENT_KEYS:
        return False
    times = moment['frame_times']
    bounds = (moment['start_time'], moment['end_time'], moment['detected_time'])
    if not (isinstance(moment['moment_id'], str) and re.fullmatch(r'ctx-\d{6}', moment['moment_id'])
            and isinstance(moment['anchors'], list)
            and 1 <= len(moment['anchors']) <= MAX_ANCHORS
            and all(isinstance(a, dict) and set(a) == {'channel', 'event_id'}
                    and a['channel'] in ANCHOR_CHANNELS and isinstance(a['event_id'], str)
                    and 1 <= len(a['event_id']) <= 64 for a in moment['anchors'])
            and len({(a['channel'], a['event_id']) for a in moment['anchors']})
            == len(moment['anchors'])
            and all(map(_finite, bounds))
            and 0 <= bounds[0] <= bounds[1] <= bounds[2] <= decoded
            and moment['activity'] == activity_at(segments, bounds[1])
            and isinstance(times, list) and MIN_FRAMES <= len(times) <= MAX_FRAMES
            and all(map(_finite, times))
            and all(a < b for a, b in zip(times, times[1:]))
            and bounds[0] <= times[0] and times[-1] <= bounds[1]):
        return False
    if moment['status'] == 'read':
        return (moment['failure'] is None
                and _valid_observation(moment['observation'], moment['activity']))
    return (moment['status'] == 'unread' and moment['observation'] is None
            and isinstance(moment['failure'], str) and _CODE.fullmatch(moment['failure']))


def context_events(moments):
    """Notes derived from read moments, in moment order."""
    return [{'event_id': moment['moment_id'], 'kind': EVENT_KIND,
             'start_time': moment['start_time'], 'end_time': moment['end_time'],
             'detected_time': moment['detected_time'],
             'evidence_times': list(moment['frame_times']),
             'details': dict(moment['observation']), 'clinician_confirmation': 'pending'}
            for moment in moments if moment['status'] == 'read']


def validate_context_channel_document(document, source_duration):
    """Validate one context reading; raise ValueError('invalid_context_channel_document')."""
    try:
        config = document['config']
        if (not isinstance(document, dict) or set(document) != DOCUMENT_KEYS
                or document['schema_version'] != 3
                or document['kind'] != 'context_channel_reading'
                or not _sha(document['source_sha256'])
                or not _sha(document['tracking_candidate_sha256'])
                or not _finite(source_duration) or source_duration <= 0
                or not _finite(document['decoded_seconds'])
                or not 0 < document['decoded_seconds'] <= source_duration
                or not isinstance(config, dict) or set(config) != CONFIG_KEYS
                or not isinstance(config['model'], str) or not _NAME.fullmatch(config['model'])
                or not isinstance(config['provider'], str)
                or not _NAME.fullmatch(config['provider'])
                or config['prompt_sha256'] != PROMPT_SHA256
                or config['max_frames_per_moment'] not in range(MIN_FRAMES, MAX_FRAMES + 1)
                or not isinstance(document['moments'], list)
                or len(document['moments']) > MAX_MOMENTS):
            raise ValueError
        segments = document['activity_segments']
        _validate_segments(segments, document['decoded_seconds'])
        moments = document['moments']
        if (not all(_valid_moment(m, document['decoded_seconds'], segments) for m in moments)
                or len({m['moment_id'] for m in moments}) != len(moments)
                or any(len(m['frame_times']) > config['max_frames_per_moment'] for m in moments)
                or any(b['start_time'] < a['start_time'] for a, b in zip(moments, moments[1:]))):
            raise ValueError
        expected = context_events(moments)
        events = document['events']
        if not isinstance(events, list) or len(events) != len(expected):
            raise ValueError
        for event, derived in zip(events, expected):
            if (not isinstance(event, dict) or set(event) != set(derived)
                    or event['clinician_confirmation'] not in CLINICIAN_CONFIRMATIONS
                    or {k: v for k, v in event.items() if k != 'clinician_confirmation'}
                    != {k: v for k, v in derived.items() if k != 'clinician_confirmation'}):
                raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError('invalid_context_channel_document') from None
    return copy.deepcopy(document)


def encode_context_channel_document(document, source_duration):
    validated = validate_context_channel_document(document, source_duration)
    return json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
