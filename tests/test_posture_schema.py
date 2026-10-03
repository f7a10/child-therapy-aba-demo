"""Strict, self-consistent posture reading document."""
import copy
import json
import unittest

SOURCE = 'a' * 64
TRACKING = 'b' * 64


def config():
    return {'weights': 'yolo11s-pose.pt', 'keypoint_confidence': 0.5,
            'standing_min_ratio': 0.4, 'sitting_max_ratio': 0.25, 'min_stable_samples': 3,
            'max_gap_seconds': 3.0, 'match_iou_min': 0.5}


def samples():
    ratios = [0.6, 0.62, 0.58, 0.3, -0.2, -0.25, -0.3, None]
    rows = []
    for index, ratio in enumerate(ratios):
        from aba_demo.posture_features import classify_posture
        rows.append({'time': round(index * 0.2, 3), 'frame_index': index * 6,
                     'identity': 'confirmed', 'state': classify_posture(ratio),
                     'leg_ratio': ratio})
    rows.append({'time': 1.6, 'frame_index': 48, 'identity': 'uncertain', 'state': None,
                 'leg_ratio': None})
    return rows


def document(**overrides):
    value = {'schema_version': 1, 'kind': 'posture_reading', 'source_sha256': SOURCE,
             'tracking_candidate_sha256': TRACKING, 'config': config(),
             'decoded_seconds': 2.0, 'samples': samples(),
             'events': [{'event_id': 'pos-000000', 'kind': 'stand_to_sit', 'start_time': 0.4,
                         'end_time': 0.8, 'evidence_times': [0.4, 0.8], 'detected_time': 1.2,
                         'clinician_confirmation': 'pending'}]}
    value.update(overrides)
    return value


class PostureDocumentTests(unittest.TestCase):
    def test_valid_document_round_trips_canonically(self):
        from aba_demo.posture_schema import encode_posture_document, validate_posture_document

        encoded = encode_posture_document(document(), 2.5)
        self.assertEqual(encoded, encode_posture_document(json.loads(encoded), 2.5))
        self.assertEqual(validate_posture_document(document(), 2.5)['events'][0]['kind'],
                         'stand_to_sit')

    def test_events_must_be_exactly_what_the_samples_support(self):
        from aba_demo.posture_schema import validate_posture_document

        fabricated = document()
        fabricated['events'].append({'event_id': 'pos-000001', 'kind': 'sit_to_stand',
                                     'start_time': 1.0, 'end_time': 1.2,
                                     'evidence_times': [1.0, 1.2], 'detected_time': 1.2,
                                     'clinician_confirmation': 'pending'})
        early = document()
        early['events'][0]['detected_time'] = 0.8
        moved = document()
        moved['events'][0]['end_time'] = 1.0
        moved['events'][0]['evidence_times'] = [0.4, 1.0]
        missing = document(events=[])
        for value in (fabricated, early, moved, missing):
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
                validate_posture_document(value, 2.5)

    def test_samples_must_be_ordered_consistent_and_identity_gated(self):
        from aba_demo.posture_schema import validate_posture_document

        def changed(index, **values):
            value = document()
            value['samples'][index].update(values)
            return value

        cases = [
            changed(0, state='sitting'),
            changed(3, state='standing'),
            changed(8, state='sitting'),
            changed(8, leg_ratio=0.5),
            changed(2, time=0.1),
            changed(2, frame_index=3),
            changed(0, extra=True),
            changed(1, leg_ratio=float('nan')),
        ]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
                validate_posture_document(value, 2.5)

    def test_header_config_and_bounds_are_strict(self):
        from aba_demo.posture_schema import validate_posture_document

        inverted = config()
        inverted['sitting_max_ratio'] = 0.5
        cases = [document(kind='movement_reading'), document(source_sha256='A' * 64),
                 document(config=inverted), document(decoded_seconds=1.0),
                 document(decoded_seconds=3.0), {**document(), 'extra': 1},
                 document(samples=[])]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
                validate_posture_document(value, 2.5)
        confirmed = copy.deepcopy(document())
        confirmed['events'][0]['clinician_confirmation'] = 'auto'
        with self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
            validate_posture_document(confirmed, 2.5)


if __name__ == '__main__':
    unittest.main()
