"""Strict, self-consistent large-movement reading document."""
import copy
import json
import unittest

SOURCE = 'a' * 64
TRACKING = 'b' * 64
IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def config():
    return {'weights': 'yolo11s-pose.pt', 'keypoint_confidence': 0.5, 'match_iou_min': 0.5,
            'displacement_threshold': 1.0, 'window_seconds': 2.0, 'merge_gap_seconds': 1.0,
            'max_gap_seconds': 1.0, 'max_camera_shift': 0.1, 'max_camera_scale_change': 0.1,
            'min_camera_inliers': 12}


def samples():
    xs = [0.5, 0.5, 0.65, 0.8, 0.8, None, 0.8, 0.8]
    rows = []
    for index, x in enumerate(xs):
        row = {'time': round(index * 0.2, 3), 'frame_index': index * 6,
               'identity': 'confirmed', 'state': 'measured', 'centre': [x, 0.5],
               'torso': 0.2, 'camera': list(IDENTITY)}
        if index == 0:
            row.update(state='segment_start', camera=None)
        if x is None:
            row.update(state='not_measurable', centre=None, torso=None, camera=None)
        rows.append(row)
    rows.append({'time': 1.6, 'frame_index': 48, 'identity': 'uncertain', 'state': None,
                 'centre': None, 'torso': None, 'camera': None})
    return rows


def document(**overrides):
    value = {'schema_version': 1, 'kind': 'large_movement_reading', 'source_sha256': SOURCE,
             'tracking_candidate_sha256': TRACKING, 'config': config(),
             'decoded_seconds': 2.0, 'samples': samples(),
             'events': [{'event_id': 'lmv-000000', 'kind': 'large_movement', 'start_time': 0.2,
                         'end_time': 0.6, 'evidence_times': [0.2, 0.4, 0.6],
                         'detected_time': 1.6, 'clinician_confirmation': 'pending'}]}
    value.update(overrides)
    return value


class LargeMovementDocumentTests(unittest.TestCase):
    def validate(self, value):
        from aba_demo.large_movement_schema import validate_large_movement_document
        return validate_large_movement_document(value, 2.5)

    def test_valid_document_round_trips_canonically(self):
        from aba_demo.large_movement_schema import encode_large_movement_document

        encoded = encode_large_movement_document(document(), 2.5)
        self.assertEqual(encoded, encode_large_movement_document(json.loads(encoded), 2.5))
        self.assertEqual(self.validate(document())['events'][0]['kind'], 'large_movement')

    def test_events_must_be_exactly_what_the_samples_support(self):
        fabricated = document()
        fabricated['events'].append({'event_id': 'lmv-000001', 'kind': 'large_movement',
                                     'start_time': 1.0, 'end_time': 1.4,
                                     'evidence_times': [1.0, 1.4], 'detected_time': 1.4,
                                     'clinician_confirmation': 'pending'})
        early = document()
        early['events'][0]['detected_time'] = 0.6
        moved = document()
        moved['events'][0]['end_time'] = 1.0
        missing = document(events=[])
        duplicate = document()
        duplicate['events'][0]['event_id'] = ''
        for value in (fabricated, early, moved, missing, duplicate):
            with self.subTest(), self.assertRaisesRegex(ValueError,
                                                        'invalid_large_movement_document'):
                self.validate(value)

    def test_samples_must_be_ordered_consistent_and_identity_gated(self):
        def changed(index, **values):
            value = document()
            value['samples'][index].update(values)
            return value

        cases = [
            changed(0, state='measured'),
            changed(1, state='segment_start'),
            changed(0, camera=list(IDENTITY)),
            changed(5, camera=list(IDENTITY)),
            changed(5, centre=[0.5, 0.5]),
            changed(8, centre=[0.5, 0.5]),
            changed(8, state='not_measurable'),
            changed(2, camera=[1.0, 0.0, 0.5, 0.0, 1.0, 0.0]),
            changed(2, torso=0.001),
            changed(2, centre=[0.5]),
            changed(2, centre=[0.5, float('nan')]),
            changed(2, time=0.1),
            changed(2, frame_index=3),
            changed(0, extra=True),
        ]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError,
                                                        'invalid_large_movement_document'):
                self.validate(value)

    def test_header_config_and_bounds_are_strict(self):
        bad_config = config()
        bad_config['window_seconds'] = 0
        missing_key = config()
        del missing_key['min_camera_inliers']
        cases = [document(kind='posture_reading'), document(source_sha256='A' * 64),
                 document(config=bad_config), document(config=missing_key),
                 document(decoded_seconds=1.0), document(decoded_seconds=3.0),
                 {**document(), 'extra': 1}, document(samples=[]), document(schema_version=2)]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError,
                                                        'invalid_large_movement_document'):
                self.validate(value)
        confirmed = copy.deepcopy(document())
        confirmed['events'][0]['clinician_confirmation'] = 'auto'
        with self.assertRaisesRegex(ValueError, 'invalid_large_movement_document'):
            self.validate(confirmed)


if __name__ == '__main__':
    unittest.main()
