"""Context v2 (pilot): what happened before, during and after a measured moment.

ABA practice records the observable antecedent and consequence around a behavior
(A-B-C). For each moment the local channels marked, up to four frames are sent:
BEFORE (about 3 s earlier), MOMENT START, MOMENT END and AFTER (about 3 s later).
Every frame shows the same confirmed child binding with no identity gap between
it and the moment; a before/after frame that cannot meet that is left out and its
question is not asked. Answers are closed enums about visible actions and
positions only: never feelings, attention, intent, reasons, behavior function or
diagnosis. ``child_position_after`` gives a second look at the measured change; the
comparison with the measurement is done locally (``second_opinion``) and only
marks a moment for review. Raw model output is never kept.
"""

import copy
import hashlib
import json
import math
import re

from .activities import _validate_segments, activity_at
from .context_channel_schema import _unique_object
from .movement_windows import _target_samples
from .openrouter_context import VisualTask
from .posture_schema import CLINICIAN_CONFIRMATIONS

ROLES = ('before', 'start', 'end', 'after')
LEAD_SECONDS = 3.0
# A before/after frame is searched within this distance of the moment, nearest to LEAD_SECONDS.
MIN_GAP_SECONDS, MAX_GAP_SECONDS = 1.0, 5.0
ADULT_MOVES = ('moved_closer', 'moved_away', 'stayed', 'no_adult_visible', 'not_observable')
MATERIAL_CHANGES = ('added', 'removed', 'no_change', 'not_observable')
FIELD_VALUES = {
    'child_separable': ('yes', 'no'),
    'child_location': ('at_table', 'away_from_table', 'walking', 'on_floor', 'not_observable'),
    'child_position_after': ('seated', 'standing', 'walking', 'on_floor', 'held_by_adult',
                             'not_observable'),
    'adult_proximity': ('close', 'farther', 'no_adult_visible', 'not_observable'),
    'task_materials_near_child': ('present', 'absent', 'not_observable'),
    'adult_movement_before': ADULT_MOVES,
    'materials_change_before': MATERIAL_CHANGES,
    'adult_movement_after': ADULT_MOVES,
    'materials_change_after': MATERIAL_CHANGES,
}
LAYOUTS = (ROLES, ROLES[1:], ROLES[:3], ROLES[1:3])
BASE_FIELDS = ('child_separable', 'child_location', 'child_position_after', 'adult_proximity',
               'task_materials_near_child')
MAX_OUTPUT_CHARS = 2048

_INTRO = """You see {count} frames from a recorded therapy session, in time order.
Frame roles by position: {layout}.
In each scene image the selected CHILD is outlined in green; other people (adults) are
outlined in red. The second image of each frame is an unannotated close-up of the child's area.
Answer only what is directly visible in these frames. Never describe feelings, attention,
intentions, reasons, behavior meaning or diagnosis. Prefer not_observable or no_change over
guessing.
"""
_QUESTIONS = {
    'child_separable': """child_separable: yes only if in every frame you can tell which body
parts are the green-outlined child's and which belong to the red-outlined people; otherwise no.
""",
    'child_location': """child_location (MOMENT START and END frames): at_table if the child is at
or seated at a table; away_from_table if the child is upright away from any table; walking if
the child is visibly stepping between these frames; on_floor if sitting, lying or crawling on
the floor; not_observable if it cannot be seen.
""",
    'child_position_after': """child_position_after ({settled} frame only): seated on a chair or
seat; standing; walking (mid-step, moving); on_floor; held_by_adult if an adult is carrying or
holding the child up; not_observable.
""",
    'adult_proximity': """adult_proximity (MOMENT START and END frames, the red-outlined adult closest
to the child): close if within about an arm's length (including any contact); farther;
no_adult_visible; not_observable.
""",
    'task_materials_near_child': """task_materials_near_child (MOMENT frames): present if toys or task
materials lie on the table or surface within the child's reach; absent; not_observable.
""",
    'adult_movement_before': """adult_movement_before: from the BEFORE frame to the MOMENT START frame,
did the closest red-outlined adult's body move closer to the child, move away, or stay about as
far (stayed)? no_adult_visible; not_observable.
""",
    'materials_change_before': """materials_change_before: from the BEFORE frame to the MOMENT START
frame, were objects added to or removed from the table area in front of the child, or no_change?
not_observable if that area is hidden.
""",
    'adult_movement_after': """adult_movement_after: the same question from the MOMENT END frame to the
AFTER frame.
""",
    'materials_change_after': """materials_change_after: the same question from the MOMENT END frame to
the AFTER frame.
""",
}
_OUTRO = """If child_separable is no, every other field must be not_observable."""
_ROLE_TEXT = {'before': 'BEFORE (about 3 s before the moment)', 'start': 'MOMENT START',
              'end': 'MOMENT END', 'after': 'AFTER (about 3 s after the moment)'}


def fields_for(roles):
    """The questions a window with these frame roles can answer."""
    fields = list(BASE_FIELDS)
    if 'before' in roles:
        fields += ['adult_movement_before', 'materials_change_before']
    if 'after' in roles:
        fields += ['adult_movement_after', 'materials_change_after']
    return tuple(fields)


def prompt_for(roles):
    layout = ', '.join(f'{position} = {_ROLE_TEXT[role]}' for position, role in enumerate(roles))
    # The settled position is read after the change; without an AFTER frame, at its end.
    settled = 'AFTER' if 'after' in roles else 'MOMENT END'
    return (_INTRO.format(count=len(roles), layout=layout)
            + ''.join(_QUESTIONS[name].replace('{settled}', settled)
                      for name in fields_for(roles)) + _OUTRO)


def valid_observation(value, roles):
    fields = fields_for(roles)
    return (isinstance(value, dict) and set(value) == set(fields)
            and all(value[name] in FIELD_VALUES[name] for name in fields)
            and (value['child_separable'] == 'yes'
                 or all(value[name] == 'not_observable' for name in fields
                        if name != 'child_separable')))


def task_for(roles):
    """A strict closed-enum task for one frame layout."""
    roles = tuple(roles)
    if roles not in LAYOUTS:
        raise ValueError('invalid_context_layout')
    fields = fields_for(roles)

    def output_schema(frame_count):
        if frame_count != len(roles):
            raise ValueError('invalid_context_window')
        return {'type': 'object', 'additionalProperties': False,
                'properties': {name: {'type': 'string', 'enum': list(FIELD_VALUES[name])}
                               for name in fields},
                'required': list(fields)}

    def parse(raw, times):
        if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_OUTPUT_CHARS:
            raise ValueError('invalid_context:size')
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except ValueError as error:
            if str(error).startswith('invalid_context'):
                raise
            raise ValueError('invalid_context:json') from None
        if not isinstance(value, dict) or set(value) != set(fields):
            raise ValueError('invalid_context:fields')
        if not all(value[name] in FIELD_VALUES[name] for name in fields):
            raise ValueError('invalid_context:enum')
        if not valid_observation(value, roles):
            raise ValueError('invalid_context:separable')
        return value

    name = 'aba_context_v2_' + '_'.join(role[0] for role in roles)
    return VisualTask(name=name, prompt=prompt_for(roles), output_schema=output_schema,
                      parse=parse)


PROMPT_TEMPLATE_SHA256 = hashlib.sha256(
    json.dumps({str(roles): prompt_for(roles) for roles in LAYOUTS},
               sort_keys=True).encode('utf-8')).hexdigest()


def _binding_runs(audit):
    """Prefix count of identity breaks: frames i..j share one binding iff counts match."""
    breaks, counts = 0, []
    for index, row in enumerate(audit):
        previous = audit[index - 1] if index else None
        if (row['identity'] != 'confirmed' or previous is not None
                and (previous['identity'] != 'confirmed'
                     or previous['target_id'] != row['target_id'])):
            breaks += 1
        counts.append(breaks)
    return counts


EDGE_MARGIN = 0.01


def inside_frame(box, margin=EDGE_MARGIN):
    return (box[0] >= margin and box[1] >= margin
            and box[2] <= 1 - margin and box[3] <= 1 - margin)


def plan_v2_frames(data, moment_frames):
    """Frames for one v1 moment: before/start/end/after with roles.

    ``moment_frames`` are the moment's planned frames (time order, confirmed, one
    target). START and END are its first and last; BEFORE and AFTER are confirmed
    samples on the same unbroken binding with the child wholly in the picture,
    nearest to 3 s outside the moment.
    """
    audit = data['provenance']['causal_audit']
    runs = _binding_runs(audit)
    targets = _target_samples(data)
    time_of = {row['frame_index']: row['time'] for row in audit}
    start, end = moment_frames[0], moment_frames[-1]
    run = runs[start['frame_index']]
    if runs[end['frame_index']] != run:
        raise ValueError('moment_crosses_identity_gap')

    def frame(index):
        target_id, box, overlap, others = targets[index]
        return {'frame_index': index, 'time': time_of[index], 'target_box': list(box),
                'other_boxes': [list(other) for other in others]}

    def nearest(reference, sign):
        # The child must be wholly in the picture: a body cut by the frame edge misleads.
        candidates = [index for index in targets
                      if runs[index] == run and inside_frame(targets[index][1])
                      and MIN_GAP_SECONDS <= sign * (time_of[index] - reference) <= MAX_GAP_SECONDS]
        if not candidates:
            return None
        return min(candidates, key=lambda index: (abs(abs(time_of[index] - reference)
                                                       - LEAD_SECONDS), index))

    before = nearest(start['time'], -1)
    after = nearest(end['time'], +1)
    planned = []
    if before is not None:
        planned.append(('before', frame(before)))
    planned.append(('start', frame(start['frame_index'])))
    planned.append(('end', frame(end['frame_index'])))
    if after is not None:
        planned.append(('after', frame(after)))
    return [role for role, _ in planned], [item for _, item in planned]


# Measured change -> positions at the moment's end that agree / disagree with it.
_EXPECTED = {
    ('posture', 'sit_to_stand'): ({'standing', 'walking'}, {'seated', 'on_floor'}),
    ('posture', 'stand_to_sit'): ({'seated'}, {'standing', 'walking'}),
    ('movement', 'large_movement'): ({'walking', 'standing'}, {'seated'}),
}


def second_opinion(anchor_kinds, observation):
    """'agrees', 'disagrees' or 'unclear' for the measured changes of a moment."""
    position = (observation or {}).get('child_position_after')
    verdicts = []
    for kind in anchor_kinds:
        expected = _EXPECTED.get(kind)
        if expected is None or position in (None, 'not_observable', 'held_by_adult'):
            continue
        agree, disagree = expected
        verdicts.append('agrees' if position in agree else
                        'disagrees' if position in disagree else 'unclear')
    if 'disagrees' in verdicts:
        return 'disagrees'
    return 'agrees' if verdicts and all(v == 'agrees' for v in verdicts) else 'unclear'


# ----- document (pending, source- and tracking-bound) -----

DOCUMENT_KIND = 'context_v2_reading'
SCHEMA_VERSION = 1
MAX_FRAMES_PER_MOMENT = len(ROLES)
# Shown with each note (the event's ``details``, at most 8 short tokens with second_opinion).
DETAIL_FIELDS = ('child_separable', 'child_location', 'child_position_after',
                 'adult_movement_before', 'adult_movement_after',
                 'materials_change_before', 'materials_change_after')
SECOND_OPINIONS = ('agrees', 'disagrees', 'unclear')
EVENT_KIND = 'context_note'
DOCUMENT_KEYS = frozenset({'schema_version', 'kind', 'source_sha256',
                           'tracking_candidate_sha256', 'decoded_seconds', 'config',
                           'activity_segments', 'moments', 'events'})
CONFIG_KEYS = frozenset({'model', 'provider', 'prompt_template_sha256', 'max_frames_per_moment'})
MOMENT_KEYS = frozenset({'moment_id', 'anchors', 'start_time', 'end_time', 'detected_time',
                         'activity', 'roles', 'frame_times', 'status', 'failure',
                         'observation', 'second_opinion'})
ANCHOR_KINDS = {'posture': ('sit_to_stand', 'stand_to_sit'), 'movement': ('large_movement',),
                'orientation': ('turned_away_from_task', 'turned_back_to_task')}
MAX_ANCHORS = 8
MAX_MOMENTS = 200
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}')
_CODE = re.compile(r'[a-z][a-z0-9_:]{0,79}')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= set('0123456789abcdef')


def _valid_moment(moment, decoded, segments):
    if not isinstance(moment, dict) or set(moment) != MOMENT_KEYS:
        return False
    roles, times = moment['roles'], moment['frame_times']
    bounds = (moment['start_time'], moment['end_time'], moment['detected_time'])
    if not (isinstance(moment['moment_id'], str)
            and re.fullmatch(r'ctx-\d{6}', moment['moment_id'])
            and isinstance(moment['anchors'], list)
            and 1 <= len(moment['anchors']) <= MAX_ANCHORS
            and all(isinstance(a, dict) and set(a) == {'channel', 'event_id', 'kind'}
                    and a['kind'] in ANCHOR_KINDS.get(a['channel'], ())
                    and isinstance(a['event_id'], str) and 1 <= len(a['event_id']) <= 64
                    for a in moment['anchors'])
            and all(map(_finite, bounds))
            and 0 <= bounds[0] <= bounds[1] <= bounds[2] <= decoded
            and moment['activity'] == activity_at(segments, bounds[1])
            and isinstance(roles, list) and tuple(roles) in LAYOUTS
            and isinstance(times, list) and len(times) == len(roles)
            and all(map(_finite, times)) and all(a < b for a, b in zip(times, times[1:]))
            and 0 <= times[0] and times[-1] <= decoded
            and all(bounds[0] <= time <= bounds[1]
                    for role, time in zip(roles, times) if role in ('start', 'end'))):
        return False
    kinds = [(a['channel'], a['kind']) for a in moment['anchors']]
    if moment['status'] == 'read':
        return (moment['failure'] is None
                and valid_observation(moment['observation'], tuple(roles))
                and moment['second_opinion'] == second_opinion(kinds, moment['observation']))
    return (moment['status'] == 'unread' and moment['observation'] is None
            and moment['second_opinion'] is None
            and isinstance(moment['failure'], str)
            and _CODE.fullmatch(moment['failure']) is not None)


def context_v2_events(moments):
    """One suggested note per read moment; its evidence is the moment's own frames."""
    return [{'event_id': moment['moment_id'], 'kind': EVENT_KIND,
             'start_time': moment['start_time'], 'end_time': moment['end_time'],
             'detected_time': moment['detected_time'],
             'evidence_times': [time for role, time in zip(moment['roles'],
                                                           moment['frame_times'])
                                if role in ('start', 'end')],
             'details': {**{name: moment['observation'][name] for name in DETAIL_FIELDS
                            if name in moment['observation']},
                         'second_opinion': moment['second_opinion']},
             'clinician_confirmation': 'pending'}
            for moment in moments if moment['status'] == 'read']


def validate_context_v2_document(document, source_duration):
    """Validate one v2 reading; raise ValueError('invalid_context_v2_document')."""
    try:
        config = document['config']
        if (not isinstance(document, dict) or set(document) != DOCUMENT_KEYS
                or document['schema_version'] != SCHEMA_VERSION
                or document['kind'] != DOCUMENT_KIND
                or not _sha(document['source_sha256'])
                or not _sha(document['tracking_candidate_sha256'])
                or not _finite(source_duration) or source_duration <= 0
                or not _finite(document['decoded_seconds'])
                or not 0 < document['decoded_seconds'] <= source_duration
                or not isinstance(config, dict) or set(config) != CONFIG_KEYS
                or not isinstance(config['model'], str) or not _NAME.fullmatch(config['model'])
                or not isinstance(config['provider'], str)
                or not _NAME.fullmatch(config['provider'])
                or config['prompt_template_sha256'] != PROMPT_TEMPLATE_SHA256
                or config['max_frames_per_moment'] != MAX_FRAMES_PER_MOMENT
                or not isinstance(document['moments'], list)
                or len(document['moments']) > MAX_MOMENTS):
            raise ValueError
        segments = document['activity_segments']
        _validate_segments(segments, document['decoded_seconds'])
        moments = document['moments']
        if (not all(_valid_moment(m, document['decoded_seconds'], segments) for m in moments)
                or len({m['moment_id'] for m in moments}) != len(moments)
                or any(b['start_time'] < a['start_time'] for a, b in zip(moments, moments[1:]))):
            raise ValueError
        expected = context_v2_events(moments)
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
        raise ValueError('invalid_context_v2_document') from None
    return copy.deepcopy(document)


def encode_context_v2_document(document, source_duration):
    validated = validate_context_v2_document(document, source_duration)
    return json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
