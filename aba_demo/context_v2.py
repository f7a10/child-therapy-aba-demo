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

import hashlib
import json

from .context_channel_schema import _unique_object
from .movement_windows import _target_samples
from .openrouter_context import VisualTask

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
