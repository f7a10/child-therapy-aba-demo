"""Strict, self-consistent contract for a local posture reading.

The document keeps every confirmed 5 Hz sample with its measured leg ratio and
derived state, and the posture-change events. Validation recomputes states from
ratios and events from samples, so an edited or fabricated event cannot pass.
Version 2 adds per sample the torso angle (``lying``), the hip height and torso
length, the reason a sample is not measurable and the carried-over (``held``)
posture, which validation also recomputes. Version 1 readings stay valid.
Uncertain identity carries no posture. This channel is separate from the pose
``signals`` and never fills them.
"""

import json
import math

from .posture_features import (
    EVENT_KINDS, EVENT_KINDS_V2, GAP_REASONS, POSTURE_STATES, POSTURE_STATES_V2, classify_posture,
    classify_posture_v2, held_postures, posture_events)


CONFIG_KEYS = frozenset({'weights', 'keypoint_confidence', 'standing_min_ratio',
                         'sitting_max_ratio', 'min_stable_samples', 'max_gap_seconds',
                         'match_iou_min'})
DOCUMENT_KEYS = frozenset({'schema_version', 'kind', 'source_sha256',
                           'tracking_candidate_sha256', 'config', 'decoded_seconds',
                           'samples', 'events'})
SAMPLE_KEYS = frozenset({'time', 'frame_index', 'identity', 'state', 'leg_ratio'})
SAMPLE_KEYS_V2 = SAMPLE_KEYS | {'torso_angle', 'thigh_angle', 'hip_y', 'torso', 'reason', 'held'}
CONFIG_KEYS_V2 = frozenset({'lying_min_degrees', 'lying_min_thigh_degrees', 'hold_max_hip_shift',
                            'hold_max_identity_gap', 'standing_needs_both_knees'})
EVENT_KEYS = frozenset({'event_id', 'kind', 'start_time', 'end_time', 'evidence_times',
                        'detected_time', 'clinician_confirmation'})
CLINICIAN_CONFIRMATIONS = ('pending', 'confirmed', 'rejected')
MAX_SAMPLES = 100_000
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA_CHARACTERS


def _valid_config(config, version=1):
    # Version 1 readings from before the both-knees rule have no such key (rule off).
    allowed = ((CONFIG_KEYS | CONFIG_KEYS_V2,) if version == 2
               else (CONFIG_KEYS, CONFIG_KEYS | {'standing_needs_both_knees'}))
    if not isinstance(config, dict):
        return False
    if version == 2 and not (_finite(config.get('lying_min_degrees'))
                             and 0 < config['lying_min_degrees'] < 90
                             and _finite(config.get('lying_min_thigh_degrees'))
                             and 0 <= config['lying_min_thigh_degrees'] < 90
                             and _finite(config.get('hold_max_hip_shift'))
                             and 0 < config['hold_max_hip_shift'] <= 2
                             and _finite(config.get('hold_max_identity_gap'))
                             and 0 <= config['hold_max_identity_gap'] <= 10):
        return False
    return (isinstance(config, dict)
            and set(config) in allowed
            and type(config.get('standing_needs_both_knees', False)) is bool
            and isinstance(config['weights'], str) and 1 <= len(config['weights']) <= 128
            and _finite(config['keypoint_confidence']) and 0 < config['keypoint_confidence'] < 1
            and _finite(config['standing_min_ratio']) and _finite(config['sitting_max_ratio'])
            and config['sitting_max_ratio'] < config['standing_min_ratio']
            and type(config['min_stable_samples']) is int
            and 2 <= config['min_stable_samples'] <= 20
            and _finite(config['max_gap_seconds']) and 0 < config['max_gap_seconds'] <= 60
            and _finite(config['match_iou_min']) and 0 < config['match_iou_min'] <= 1)


def _optional(value):
    return value is None or _finite(value)


def _valid_sample_v2(sample, config, decoded):
    if (not isinstance(sample, dict) or set(sample) != SAMPLE_KEYS_V2
            or not _finite(sample['time']) or not 0 <= sample['time'] <= decoded
            or type(sample['frame_index']) is not int or sample['frame_index'] < 0
            or sample['identity'] not in ('confirmed', 'uncertain')
            or not all(_optional(sample[key])
                       for key in ('leg_ratio', 'torso_angle', 'thigh_angle', 'hip_y', 'torso'))):
        return False
    measures = (sample['torso_angle'], sample['hip_y'], sample['torso'])
    if sample['identity'] == 'uncertain':
        return (sample['state'] is None and sample['leg_ratio'] is None and sample['reason'] is None
                and sample['held'] is None and sample['thigh_angle'] is None
                and measures == (None, None, None))
    if (measures.count(None) not in (0, 3)
            or (measures[0] is None and sample['thigh_angle'] is not None)
            or (sample['torso'] is not None and sample['torso'] <= 0)):
        return False
    state = classify_posture_v2(sample['leg_ratio'], sample['torso_angle'], sample['thigh_angle'],
                                standing_min=config['standing_min_ratio'],
                                sitting_max=config['sitting_max_ratio'],
                                lying_min=config['lying_min_degrees'],
                                lying_min_thigh=config['lying_min_thigh_degrees'])
    if sample['state'] != state or state not in POSTURE_STATES_V2:
        return False
    if state == 'not_measurable':
        return sample['reason'] in GAP_REASONS and (sample['reason'] != 'no_pose' or measures == (None, None, None))
    return sample['reason'] is None


def _valid_sample(sample, config, decoded):
    if (not isinstance(sample, dict) or set(sample) != SAMPLE_KEYS
            or not _finite(sample['time']) or not 0 <= sample['time'] <= decoded
            or type(sample['frame_index']) is not int or sample['frame_index'] < 0
            or sample['identity'] not in ('confirmed', 'uncertain')):
        return False
    ratio = sample['leg_ratio']
    if sample['identity'] == 'uncertain':
        return sample['state'] is None and ratio is None
    if ratio is not None and not _finite(ratio):
        return False
    return (sample['state'] in POSTURE_STATES
            and sample['state'] == classify_posture(
                ratio, standing_min=config['standing_min_ratio'],
                sitting_max=config['sitting_max_ratio']))


def validate_posture_document(document, source_duration):
    """Validate one posture reading; raise ValueError('invalid_posture_document')."""
    try:
        if (not isinstance(document, dict) or set(document) != DOCUMENT_KEYS
                or document['schema_version'] not in (1, 2) or document['kind'] != 'posture_reading'
                or not _sha(document['source_sha256'])
                or not _sha(document['tracking_candidate_sha256'])
                or not _valid_config(document['config'], document['schema_version'])
                or not _finite(source_duration) or source_duration <= 0
                or not _finite(document['decoded_seconds'])
                or not 0 < document['decoded_seconds'] <= source_duration
                or not isinstance(document['samples'], list)
                or not 1 <= len(document['samples']) <= MAX_SAMPLES
                or not isinstance(document['events'], list)):
            raise ValueError
        config, samples = document['config'], document['samples']
        version = document['schema_version']
        check = _valid_sample_v2 if version == 2 else _valid_sample
        if not all(check(sample, config, document['decoded_seconds']) for sample in samples):
            raise ValueError
        if version == 2 and [sample['held'] for sample in samples] != held_postures(
                samples, min_stable_samples=config['min_stable_samples'],
                max_hip_shift=config['hold_max_hip_shift'],
                max_identity_gap=config['hold_max_identity_gap']):
            raise ValueError
        kinds = EVENT_KINDS_V2 if version == 2 else EVENT_KINDS
        if any(current['time'] <= previous['time']
               or current['frame_index'] <= previous['frame_index']
               for previous, current in zip(samples, samples[1:])):
            raise ValueError
        expected = posture_events(samples, min_stable_samples=config['min_stable_samples'],
                                  max_gap_seconds=config['max_gap_seconds'], kinds=kinds)
        events = document['events']
        identifiers = set()
        for event, derived in zip(events, expected):
            if (not isinstance(event, dict) or set(event) != EVENT_KEYS
                    or not isinstance(event['event_id'], str)
                    or not 1 <= len(event['event_id']) <= 64 or event['event_id'] in identifiers
                    or event['kind'] not in kinds.values()
                    or event['clinician_confirmation'] not in CLINICIAN_CONFIRMATIONS
                    or {key: event[key] for key in derived} != derived):
                raise ValueError
            identifiers.add(event['event_id'])
        if len(events) != len(expected):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError('invalid_posture_document') from None
    return dict(document)


def encode_posture_document(document, source_duration):
    """Return deterministic UTF-8 bytes for one validated posture document."""
    validated = validate_posture_document(document, source_duration)
    return json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
