"""Strict, self-consistent contract for a local orientation reading.

The document keeps every 5 Hz sample with its measured facing angle and facing
length and the derived state, plus the turn events. Validation recomputes states
from the measures and events from the samples, so an edited or fabricated event
cannot pass. Uncertain identity carries no orientation. The therapist-drawn task
region is part of ``config``. Each sample also keeps the same skeleton's posture
leg ratio and the camera translation since the previous sample: only a stably
seated child (causal posture rule over the sequence) under a still camera has an
orientation, and validation recomputes both gates. The label is the observable
sign "head turned away from the task region", never attention or gaze.
"""

import json
import math

from .orientation_features import (
    EVENT_KINDS, ORIENTATION_STATES, orientation_events, orientation_states, valid_task_region)


CONFIG_KEYS = frozenset({'weights', 'keypoint_confidence', 'task_region', 'toward_max_degrees',
                         'away_min_degrees', 'min_facing_length', 'min_stable_samples',
                         'max_gap_seconds', 'match_iou_min', 'standing_min_ratio',
                         'sitting_max_ratio', 'max_camera_shift',
                         'posture_min_stable_samples', 'posture_max_gap_seconds'})
DOCUMENT_KEYS = frozenset({'schema_version', 'kind', 'source_sha256',
                           'tracking_candidate_sha256', 'config', 'decoded_seconds',
                           'samples', 'events'})
SAMPLE_KEYS = frozenset({'time', 'frame_index', 'identity', 'state', 'facing_angle',
                         'facing_length', 'leg_ratio', 'camera_shift'})
EVENT_KEYS = frozenset({'event_id', 'kind', 'start_time', 'end_time', 'evidence_times',
                        'detected_time', 'clinician_confirmation'})
CLINICIAN_CONFIRMATIONS = ('pending', 'confirmed', 'rejected')
MAX_SAMPLES = 100_000
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA_CHARACTERS


def _valid_config(config):
    return (isinstance(config, dict) and set(config) == CONFIG_KEYS
            and isinstance(config['weights'], str) and 1 <= len(config['weights']) <= 128
            and _finite(config['keypoint_confidence']) and 0 < config['keypoint_confidence'] < 1
            and valid_task_region(config['task_region'])
            and _finite(config['toward_max_degrees']) and _finite(config['away_min_degrees'])
            and 0 < config['toward_max_degrees'] < config['away_min_degrees'] < 180
            and _finite(config['min_facing_length']) and 0 <= config['min_facing_length'] <= 5
            and type(config['min_stable_samples']) is int
            and 2 <= config['min_stable_samples'] <= 20
            and _finite(config['max_gap_seconds']) and 0 < config['max_gap_seconds'] <= 60
            and _finite(config['match_iou_min']) and 0 < config['match_iou_min'] <= 1
            and _finite(config['standing_min_ratio']) and _finite(config['sitting_max_ratio'])
            and config['sitting_max_ratio'] < config['standing_min_ratio']
            and _finite(config['max_camera_shift']) and 0 < config['max_camera_shift'] <= 1
            and type(config['posture_min_stable_samples']) is int
            and 2 <= config['posture_min_stable_samples'] <= 20
            and _finite(config['posture_max_gap_seconds'])
            and 0 < config['posture_max_gap_seconds'] <= 60)


def _valid_sample(sample, decoded):
    if (not isinstance(sample, dict) or set(sample) != SAMPLE_KEYS
            or not _finite(sample['time']) or not 0 <= sample['time'] <= decoded
            or type(sample['frame_index']) is not int or sample['frame_index'] < 0
            or sample['identity'] not in ('confirmed', 'uncertain')):
        return False
    angle, length = sample['facing_angle'], sample['facing_length']
    ratio, shift = sample['leg_ratio'], sample['camera_shift']
    if sample['identity'] == 'uncertain':
        return (sample['state'] is None and angle is None and length is None
                and ratio is None and shift is None)
    if ratio is not None and not _finite(ratio):
        return False
    if shift is not None and not (_finite(shift) and shift >= 0):
        return False
    if (angle is None) != (length is None):
        return False
    if angle is not None and not (_finite(angle) and 0 <= angle <= 180
                                  and _finite(length) and length >= 0):
        return False
    return sample['state'] in ORIENTATION_STATES


def validate_orientation_document(document, source_duration):
    """Validate one orientation reading; raise ValueError('invalid_orientation_document')."""
    try:
        if (not isinstance(document, dict) or set(document) != DOCUMENT_KEYS
                or document['schema_version'] != 1 or document['kind'] != 'orientation_reading'
                or not _sha(document['source_sha256'])
                or not _sha(document['tracking_candidate_sha256'])
                or not _valid_config(document['config'])
                or not _finite(source_duration) or source_duration <= 0
                or not _finite(document['decoded_seconds'])
                or not 0 < document['decoded_seconds'] <= source_duration
                or not isinstance(document['samples'], list)
                or not 1 <= len(document['samples']) <= MAX_SAMPLES
                or not isinstance(document['events'], list)):
            raise ValueError
        config, samples = document['config'], document['samples']
        if not all(_valid_sample(sample, document['decoded_seconds']) for sample in samples):
            raise ValueError
        if any(current['time'] <= previous['time']
               or current['frame_index'] <= previous['frame_index']
               for previous, current in zip(samples, samples[1:])):
            raise ValueError
        if [sample['state'] for sample in samples] != orientation_states(samples, config):
            raise ValueError
        expected = orientation_events(samples, min_stable_samples=config['min_stable_samples'],
                                      max_gap_seconds=config['max_gap_seconds'])
        events = document['events']
        identifiers = set()
        for event, derived in zip(events, expected):
            if (not isinstance(event, dict) or set(event) != EVENT_KEYS
                    or not isinstance(event['event_id'], str)
                    or not 1 <= len(event['event_id']) <= 64 or event['event_id'] in identifiers
                    or event['kind'] not in EVENT_KINDS.values()
                    or event['clinician_confirmation'] not in CLINICIAN_CONFIRMATIONS
                    or {key: event[key] for key in derived} != derived):
                raise ValueError
            identifiers.add(event['event_id'])
        if len(events) != len(expected):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError('invalid_orientation_document') from None
    return dict(document)


def encode_orientation_document(document, source_duration):
    """Return deterministic UTF-8 bytes for one validated orientation document."""
    validated = validate_orientation_document(document, source_duration)
    return json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
