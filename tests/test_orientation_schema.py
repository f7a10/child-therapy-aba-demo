"""Strict, self-consistent orientation reading document."""
import copy
import json
import unittest

SOURCE = 'a' * 64
TRACKING = 'b' * 64


def config():
    return {'weights': 'yolo11s-pose.pt', 'keypoint_confidence': 0.5,
            'task_region': [0.6, 0.5, 0.9, 0.8], 'toward_max_degrees': 60.0,
            'away_min_degrees': 100.0, 'min_facing_length': 0.25, 'min_stable_samples': 3,
            'max_gap_seconds': 3.0, 'match_iou_min': 0.5, 'standing_min_ratio': 0.4,
            'sitting_max_ratio': 0.25, 'max_camera_shift': 0.015,
            'posture_min_stable_samples': 3, 'posture_max_gap_seconds': 3.0}


def samples():
    """Stably seated from the third sample (0.2 s); hidden knees at 0.3 s keep the seat."""
    measures = [  # time, angle, length, leg_ratio, expected state
        (0.0, None, None, -0.2, 'not_measurable'),
        (0.1, 10.0, 0.6, -0.2, 'not_measurable'),
        (0.2, 12.0, 0.7, -0.2, 'toward'),
        (0.3, 8.0, 0.6, None, 'toward'),
        (0.4, 9.0, 0.6, 0.3, 'toward'),
        (0.6, 80.0, 0.6, -0.2, 'unclear'),
        (0.8, 150.0, 0.5, -0.2, 'away'),
        (1.0, 160.0, 0.6, -0.2, 'away'),
        (1.2, 170.0, 0.6, -0.2, 'away'),
        (1.4, None, None, None, 'not_measurable'),
    ]
    rows = [{'time': time, 'frame_index': round(time * 30), 'identity': 'confirmed',
             'state': state, 'facing_angle': angle, 'facing_length': length,
             'leg_ratio': ratio, 'camera_shift': 0.002}
            for time, angle, length, ratio, state in measures]
    rows.append({'time': 1.6, 'frame_index': 48, 'identity': 'uncertain', 'state': None,
                 'facing_angle': None, 'facing_length': None, 'leg_ratio': None,
                 'camera_shift': None})
    return rows


def document(**overrides):
    value = {'schema_version': 1, 'kind': 'orientation_reading', 'source_sha256': SOURCE,
             'tracking_candidate_sha256': TRACKING, 'config': config(),
             'decoded_seconds': 2.0, 'samples': samples(),
             'events': [{'event_id': 'ori-000000', 'kind': 'turned_away_from_task',
                         'start_time': 0.4, 'end_time': 0.8, 'evidence_times': [0.4, 0.8],
                         'detected_time': 1.2, 'clinician_confirmation': 'pending'}]}
    value.update(overrides)
    return value


class OrientationDocumentTests(unittest.TestCase):
    def test_valid_document_round_trips_canonically(self):
        from aba_demo.orientation_schema import (
            encode_orientation_document, validate_orientation_document)

        encoded = encode_orientation_document(document(), 2.5)
        self.assertEqual(encoded, encode_orientation_document(json.loads(encoded), 2.5))
        self.assertEqual(validate_orientation_document(document(), 2.5)['events'][0]['kind'],
                         'turned_away_from_task')

    def test_events_must_be_exactly_what_the_samples_support(self):
        from aba_demo.orientation_schema import validate_orientation_document

        fabricated = document()
        fabricated['events'].append({'event_id': 'ori-000001', 'kind': 'turned_back_to_task',
                                     'start_time': 1.0, 'end_time': 1.2,
                                     'evidence_times': [1.0, 1.2], 'detected_time': 1.2,
                                     'clinician_confirmation': 'pending'})
        early = document()
        early['events'][0]['detected_time'] = 0.8
        moved = document()
        moved['events'][0]['end_time'] = 1.0
        moved['events'][0]['evidence_times'] = [0.4, 1.0]
        renamed = document()
        renamed['events'][0]['kind'] = 'turned_back_to_task'
        missing = document(events=[])
        for value in (fabricated, early, moved, renamed, missing):
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_orientation_document'):
                validate_orientation_document(value, 2.5)

    def test_samples_must_be_ordered_consistent_and_identity_gated(self):
        from aba_demo.orientation_schema import validate_orientation_document

        def changed(index, **values):
            value = document()
            value['samples'][index].update(values)
            return value

        cases = [
            changed(0, state='toward'),
            changed(1, state='toward'),          # not yet stably seated
            changed(5, state='toward'),
            changed(6, facing_length=0.1),
            changed(9, state='away'),
            changed(10, state='toward'),
            changed(10, facing_angle=10.0, facing_length=0.6),
            changed(2, time=0.1),
            changed(2, frame_index=3),
            changed(0, extra=True),
            changed(2, facing_angle=float('nan')),
            changed(2, facing_angle=200.0),
            changed(2, facing_length=-0.5),
            changed(2, facing_length=None),
            changed(2, leg_ratio=0.6),           # the seat is not yet confirmed
            changed(1, leg_ratio=None),
            changed(2, camera_shift=0.05),
            changed(2, camera_shift=None),
            changed(9, camera_shift=-0.001),
            changed(9, leg_ratio=float('inf')),
            changed(10, camera_shift=0.0),
            changed(10, leg_ratio=-0.2),
        ]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_orientation_document'):
                validate_orientation_document(value, 2.5)

    def test_header_config_region_and_bounds_are_strict(self):
        from aba_demo.orientation_schema import validate_orientation_document

        inverted = config()
        inverted['toward_max_degrees'] = 120.0
        bad_region = config()
        bad_region['task_region'] = [0.9, 0.5, 0.6, 0.8]
        no_region = config()
        del no_region['task_region']
        no_shift = config()
        del no_shift['max_camera_shift']
        bad_shift = config()
        bad_shift['max_camera_shift'] = 0.0
        bad_posture = config()
        bad_posture['sitting_max_ratio'] = 0.5
        bad_stable = config()
        bad_stable['posture_min_stable_samples'] = 1
        no_gap = config()
        del no_gap['posture_max_gap_seconds']
        cases = [document(kind='posture_reading'), document(source_sha256='A' * 64),
                 document(config=inverted), document(config=bad_region),
                 document(config=no_region), document(config=no_shift),
                 document(config=bad_shift), document(config=bad_posture),
                 document(config=bad_stable), document(config=no_gap),
                 document(decoded_seconds=1.0),
                 document(decoded_seconds=3.0), {**document(), 'extra': 1},
                 document(samples=[])]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_orientation_document'):
                validate_orientation_document(value, 2.5)
        confirmed = copy.deepcopy(document())
        confirmed['events'][0]['clinician_confirmation'] = 'auto'
        with self.assertRaisesRegex(ValueError, 'invalid_orientation_document'):
            validate_orientation_document(confirmed, 2.5)


if __name__ == '__main__':
    unittest.main()
