"""Strict contract for VLM readings of the selected child's visible movement.

A reading compares a few time-ordered frames of one identity-confirmed window.
It describes visible topography only and never carries attention, gaze,
hyperactivity, emotion, intent, diagnosis, behavioral function or treatment.
It is a channel separate from deterministic pose signals and never fills a
missing pose measurement. ``none_visible`` means no change was visible across
the supplied frames, not that no movement occurred.
"""

import json
import math


MOVEMENT_FIELDS = {
    'body_position_change': ('none_visible', 'small', 'large', 'ambiguous', 'not_observable'),
    'posture_transition': ('none_visible', 'sit_to_stand', 'stand_to_sit', 'other',
                           'ambiguous', 'not_observable'),
    'hand_arm_movement': ('none_visible', 'visible', 'ambiguous', 'not_observable'),
    'head_turn': ('none_visible', 'visible', 'ambiguous', 'not_observable'),
}
SEPARABILITY = ('yes', 'no', 'ambiguous', 'not_observable')
ABSTAIN = frozenset({'ambiguous', 'not_observable'})
MIN_WINDOW_FRAMES = 2
MAX_WINDOW_FRAMES = 4
MIN_EVIDENCE_FRAMES = 2
MAX_MODEL_OUTPUT_CHARS = 8192


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _valid_times(times):
    return (isinstance(times, list)
            and MIN_WINDOW_FRAMES <= len(times) <= MAX_WINDOW_FRAMES
            and all(_finite_number(time) and time >= 0 for time in times)
            and all(current > previous for previous, current in zip(times, times[1:])))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid_movement_output')
        result[key] = value
    return result


def _asked_fields(fields):
    """Validate an optional ordered subset of movement fields; None means all."""
    if fields is None:
        return tuple(MOVEMENT_FIELDS)
    if (not isinstance(fields, tuple) or not fields or len(set(fields)) != len(fields)
            or not set(fields) <= set(MOVEMENT_FIELDS)):
        raise ValueError('invalid_movement_input')
    return tuple(name for name in MOVEMENT_FIELDS if name in fields)


def _output_keys(fields):
    return ('child_separable', *(key for name in fields for key in (name, name + '_frames')))


def model_output_schema(frame_count, fields=None):
    """JSON Schema for one window; evidence is per field, as supplied-frame positions.

    ``fields`` limits the question to a subset; the rest are never asked.
    """
    fields = _asked_fields(fields)
    if (type(frame_count) is not int
            or not MIN_WINDOW_FRAMES <= frame_count <= MAX_WINDOW_FRAMES):
        raise ValueError('invalid_movement_input')
    properties = {'child_separable': {'type': 'string', 'enum': list(SEPARABILITY)}}
    for name in fields:
        properties[name] = {'type': 'string', 'enum': list(MOVEMENT_FIELDS[name])}
        properties[name + '_frames'] = {
            'type': 'array',
            'items': {'type': 'integer', 'enum': list(range(frame_count))},
            'maxItems': frame_count,
            'uniqueItems': True,
        }
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(_output_keys(fields))}


def reading_violation(reading, evidence_valid):
    """Return the first broken rule as ``rule:field``, or None if the reading is valid.

    ``reading`` maps ``child_separable`` and each field to its value, and
    ``<field>_evidence`` to a strictly increasing list checked by
    ``evidence_valid``. Reasons name rules and fields only, never model text.
    """
    separable = reading['child_separable']
    if not isinstance(separable, str) or separable not in SEPARABILITY:
        return 'value:child_separable'
    for name, allowed in MOVEMENT_FIELDS.items():
        value, evidence = reading[name], reading[name + '_evidence']
        if not isinstance(value, str) or value not in allowed:
            return 'value:' + name
        if not isinstance(evidence, list) or not evidence_valid(evidence):
            return 'evidence_position:' + name
        if any(current <= previous for previous, current in zip(evidence, evidence[1:])):
            return 'evidence_order:' + name
        if value in ABSTAIN:
            if evidence:
                return 'abstain_with_evidence:' + name
        elif separable != 'yes':
            return 'claim_without_separable_child:' + name
        elif len(evidence) < MIN_EVIDENCE_FRAMES:
            return 'needs_two_frames:' + name
    return None


def parse_movement_output(raw, supplied_times, fields=None):
    """Validate one exact model result and map evidence positions to supplied times.

    Fields outside ``fields`` were not asked and are returned as not_observable.
    """
    fields = _asked_fields(fields)
    if not _valid_times(supplied_times):
        raise ValueError('invalid_movement_input')
    if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_MODEL_OUTPUT_CHARS:
        raise ValueError('invalid_movement_output:length')
    try:
        result = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        raise ValueError('invalid_movement_output:json') from None
    if not isinstance(result, dict) or set(result) != set(_output_keys(fields)):
        raise ValueError('invalid_movement_output:keys')
    separable = result['child_separable']
    reading = {'child_separable': separable}
    for name in MOVEMENT_FIELDS:
        asked = name in fields
        reading[name] = result[name] if asked else 'not_observable'
        reading[name + '_evidence'] = result[name + '_frames'] if asked else []

    def positions_valid(indices):
        return all(type(index) is int and 0 <= index < len(supplied_times)
                   for index in indices)

    violation = reading_violation(reading, positions_valid)
    if violation:
        raise ValueError('invalid_movement_output:' + violation)
    parsed = {'child_separable': separable}
    for name in MOVEMENT_FIELDS:
        parsed[name] = reading[name]
        parsed[name + '_evidence_times'] = [supplied_times[index]
                                            for index in reading[name + '_evidence']]
    return parsed


SEGMENT_STATUSES = ('analyzed', 'identity_uncertain', 'too_short', 'insufficient_frames',
                    'not_requested', 'provider_failed')
SENT_STATUSES = frozenset({'analyzed', 'provider_failed'})
ELIGIBLE_STATUSES = frozenset({'analyzed', 'provider_failed', 'not_requested'})
CLINICIAN_CONFIRMATIONS = ('pending', 'confirmed', 'rejected')
CROP_MODES = ('window_stable', 'window_stable_others_marked')
SEGMENT_KEYS = frozenset({
    'segment_id', 'start_time', 'end_time', 'status', 'target_id', 'max_other_overlap',
    'sent_frame_times', 'sent_image_sha256', 'child_separable', 'clinician_confirmation',
    *MOVEMENT_FIELDS, *(name + '_evidence_times' for name in MOVEMENT_FIELDS),
})
READING_CONFIG_KEYS = frozenset({
    'task', 'prompt_sha256', 'target_window_seconds', 'min_window_seconds',
    'frames_per_window', 'crop_mode',
})
DOCUMENT_KEYS = frozenset({
    'schema_version', 'kind', 'source_sha256', 'tracking_candidate_sha256',
    'reading_config', 'decoded_seconds', 'provenance', 'segments',
})
MAX_SEGMENTS = 10000
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _sha256_hex(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA_CHARACTERS


def _segment_id(value):
    return (isinstance(value, str) and 1 <= len(value) <= 64 and value.isascii()
            and value[0].isalnum()
            and all(character.isalnum() or character in '_-' for character in value))


def unread_segment(segment_id, start_time, end_time, status, *, target_id=None,
                   max_other_overlap=None, sent_frame_times=(), sent_image_sha256=()):
    """A window without a reading: every field not_observable, no evidence."""
    segment = {
        'segment_id': segment_id, 'start_time': start_time, 'end_time': end_time,
        'status': status, 'target_id': target_id, 'max_other_overlap': max_other_overlap,
        'sent_frame_times': list(sent_frame_times),
        'sent_image_sha256': list(sent_image_sha256),
        'child_separable': 'not_observable', 'clinician_confirmation': 'pending',
    }
    for name in MOVEMENT_FIELDS:
        segment[name] = 'not_observable'
        segment[name + '_evidence_times'] = []
    return segment


def validate_movement_segment(segment, source_duration):
    """Validate one movement segment against its window and sent frames."""
    if (not _finite_number(source_duration) or source_duration <= 0
            or not isinstance(segment, dict) or set(segment) != SEGMENT_KEYS):
        raise ValueError('invalid_movement_segment')
    start, end, status = segment['start_time'], segment['end_time'], segment['status']
    target_id, overlap = segment['target_id'], segment['max_other_overlap']
    times, hashes = segment['sent_frame_times'], segment['sent_image_sha256']
    if (not _segment_id(segment['segment_id'])
            or not _finite_number(start) or not _finite_number(end)
            or not 0 <= start < end <= source_duration
            or not isinstance(status, str) or status not in SEGMENT_STATUSES
            or not isinstance(segment['clinician_confirmation'], str)
            or segment['clinician_confirmation'] not in CLINICIAN_CONFIRMATIONS
            or not isinstance(times, list) or not isinstance(hashes, list)):
        raise ValueError('invalid_movement_segment')
    if status == 'identity_uncertain':
        identity_valid = target_id is None and overlap is None
    else:
        identity_valid = (type(target_id) is int and target_id >= 0
                          and (overlap is None and status not in ELIGIBLE_STATUSES
                               or _finite_number(overlap) and 0 <= overlap <= 1))
    if status in SENT_STATUSES:
        sent_valid = (_valid_times(times) and start <= times[0] and times[-1] <= end
                      and len(hashes) == 2 * len(times) and all(map(_sha256_hex, hashes)))
    else:
        sent_valid = not times and not hashes
    if not identity_valid or not sent_valid:
        raise ValueError('invalid_movement_segment')
    reading = {'child_separable': segment['child_separable']}
    for name in MOVEMENT_FIELDS:
        reading[name] = segment[name]
        reading[name + '_evidence'] = segment[name + '_evidence_times']
    if status == 'analyzed':
        allowed = set(times)
        valid = reading_violation(reading, lambda evidence: all(
            _finite_number(time) and time in allowed for time in evidence)) is None
    else:
        valid = (reading['child_separable'] == 'not_observable'
                 and all(segment[name] == 'not_observable'
                         and segment[name + '_evidence_times'] == []
                         for name in MOVEMENT_FIELDS))
    if not valid:
        raise ValueError('invalid_movement_segment')
    return dict(segment)


def _valid_reading_config(config):
    if not isinstance(config, dict) or set(config) != READING_CONFIG_KEYS:
        return False
    target, minimum = config['target_window_seconds'], config['min_window_seconds']
    task = config['task']
    return (isinstance(task, str) and 1 <= len(task) <= 64 and task.isascii()
            and task.replace('_', '').isalnum() and task == task.lower()
            and _sha256_hex(config['prompt_sha256'])
            and _finite_number(target) and 0.5 <= target <= 5
            and _finite_number(minimum) and 0 < minimum <= target / 2
            and type(config['frames_per_window']) is int
            and MIN_WINDOW_FRAMES <= config['frames_per_window'] <= MAX_WINDOW_FRAMES
            and config['crop_mode'] in CROP_MODES)


def validate_movement_document(document, source_duration):
    """Validate one gapless, source- and tracking-bound movement reading."""
    from .context_schema import validate_context_provenance

    if (not isinstance(document, dict) or set(document) != DOCUMENT_KEYS
            or document['schema_version'] != 1 or document['kind'] != 'movement_reading'
            or not _sha256_hex(document['source_sha256'])
            or not _sha256_hex(document['tracking_candidate_sha256'])
            or not _valid_reading_config(document['reading_config'])
            or not _finite_number(source_duration) or source_duration <= 0
            or not _finite_number(document['decoded_seconds'])
            or not 0 < document['decoded_seconds'] <= source_duration
            or not isinstance(document['segments'], list)
            or not 1 <= len(document['segments']) <= MAX_SEGMENTS):
        raise ValueError('invalid_movement_document')
    try:
        segments = [validate_movement_segment(segment, source_duration)
                    for segment in document['segments']]
        provenance = document['provenance']
        if any(segment['status'] == 'analyzed' for segment in segments):
            provenance = validate_context_provenance(provenance, document['source_sha256'])
        elif provenance is not None:
            raise ValueError
    except ValueError:
        raise ValueError('invalid_movement_document') from None
    seen, previous_end = set(), 0.0
    for segment in segments:
        if segment['segment_id'] in seen or segment['start_time'] != previous_end:
            raise ValueError('invalid_movement_document')
        seen.add(segment['segment_id'])
        previous_end = segment['end_time']
    if previous_end != document['decoded_seconds']:
        raise ValueError('invalid_movement_document')
    normalized = dict(document)
    normalized['provenance'] = provenance
    normalized['segments'] = segments
    return normalized


def encode_movement_document(document, source_duration):
    """Return deterministic UTF-8 bytes for one validated movement document."""
    validated = validate_movement_document(document, source_duration)
    return json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
