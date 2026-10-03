"""Strict, self-consistent contract for a local large-movement reading.

The document keeps every 5 Hz sample with the child's measured body centre,
torso length and the background camera step, and the large-movement episodes.
Validation recomputes sample states and episodes from those measurements, so an
edited or fabricated event cannot pass. Uncertain identity carries nothing.
"""

import json
import math

from .large_movement_features import (
    EVENT_KIND, MIN_TORSO, SAMPLE_STATES, large_movement_events, sample_states, valid_camera)
from .posture_schema import CLINICIAN_CONFIRMATIONS


CONFIG_KEYS = frozenset({'weights', 'keypoint_confidence', 'match_iou_min',
                         'displacement_threshold', 'window_seconds', 'merge_gap_seconds',
                         'max_gap_seconds', 'max_camera_shift', 'max_camera_scale_change',
                         'min_camera_inliers'})
DOCUMENT_KEYS = frozenset({'schema_version', 'kind', 'source_sha256',
                           'tracking_candidate_sha256', 'config', 'decoded_seconds',
                           'samples', 'events'})
SAMPLE_KEYS = frozenset({'time', 'frame_index', 'identity', 'state', 'centre', 'torso',
                         'camera'})
EVENT_KEYS = frozenset({'event_id', 'kind', 'start_time', 'end_time', 'evidence_times',
                        'detected_time', 'clinician_confirmation'})
MAX_SAMPLES = 100_000
_SHA_CHARACTERS = frozenset('0123456789abcdef')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA_CHARACTERS


def _bounded(value, low, high):
    return _finite(value) and low < value <= high


def _valid_config(config):
    return (isinstance(config, dict) and set(config) == CONFIG_KEYS
            and isinstance(config['weights'], str) and 1 <= len(config['weights']) <= 128
            and _finite(config['keypoint_confidence']) and 0 < config['keypoint_confidence'] < 1
            and _bounded(config['match_iou_min'], 0, 1)
            and _bounded(config['displacement_threshold'], 0, 10)
            and _bounded(config['window_seconds'], 0, 10)
            and _finite(config['merge_gap_seconds']) and 0 <= config['merge_gap_seconds'] <= 10
            and _bounded(config['max_gap_seconds'], 0, 10)
            and _bounded(config['max_camera_shift'], 0, 1)
            and _bounded(config['max_camera_scale_change'], 0, 1)
            and type(config['min_camera_inliers']) is int
            and 3 <= config['min_camera_inliers'] <= 1000)


def _valid_sample(sample, config, decoded):
    if (not isinstance(sample, dict) or set(sample) != SAMPLE_KEYS
            or not _finite(sample['time']) or not 0 <= sample['time'] <= decoded
            or type(sample['frame_index']) is not int or sample['frame_index'] < 0
            or sample['identity'] not in ('confirmed', 'uncertain')):
        return False
    centre, torso, camera = sample['centre'], sample['torso'], sample['camera']
    if sample['identity'] == 'uncertain' or centre is None:
        return centre is None and torso is None and camera is None
    return (isinstance(centre, list) and len(centre) == 2 and all(map(_finite, centre))
            and _finite(torso) and torso >= MIN_TORSO
            and (camera is None or valid_camera(
                camera, max_shift=config['max_camera_shift'],
                max_scale_change=config['max_camera_scale_change'])))


def validate_large_movement_document(document, source_duration):
    """Validate one large-movement reading; raise ValueError('invalid_large_movement_document')."""
    try:
        if (not isinstance(document, dict) or set(document) != DOCUMENT_KEYS
                or document['schema_version'] != 1
                or document['kind'] != 'large_movement_reading'
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
        if not all(_valid_sample(sample, config, document['decoded_seconds'])
                   for sample in samples):
            raise ValueError
        if any(current['time'] <= previous['time']
               or current['frame_index'] <= previous['frame_index']
               for previous, current in zip(samples, samples[1:])):
            raise ValueError
        states = sample_states(samples, max_gap_seconds=config['max_gap_seconds'])
        if any(sample['state'] != state or state is not None and state not in SAMPLE_STATES
               for sample, state in zip(samples, states)):
            raise ValueError
        expected = large_movement_events(
            samples, displacement_threshold=config['displacement_threshold'],
            window_seconds=config['window_seconds'],
            merge_gap_seconds=config['merge_gap_seconds'],
            max_gap_seconds=config['max_gap_seconds'])
        events = document['events']
        if len(events) != len(expected):
            raise ValueError
        identifiers = set()
        for event, derived in zip(events, expected):
            if (not isinstance(event, dict) or set(event) != EVENT_KEYS
                    or not isinstance(event['event_id'], str)
                    or not 1 <= len(event['event_id']) <= 64 or event['event_id'] in identifiers
                    or event['kind'] != EVENT_KIND
                    or event['clinician_confirmation'] not in CLINICIAN_CONFIRMATIONS
                    or {key: event[key] for key in derived} != derived):
                raise ValueError
            identifiers.add(event['event_id'])
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError('invalid_large_movement_document') from None
    return dict(document)


def encode_large_movement_document(document, source_duration):
    """Return deterministic UTF-8 bytes for one validated large-movement document."""
    validated = validate_large_movement_document(document, source_duration)
    return json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
