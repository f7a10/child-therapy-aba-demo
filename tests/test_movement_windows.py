"""Identity-gated movement window planning from a finished tracking candidate."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from movement_fixtures import OTHER_BOX, TARGET_BOX, candidate

SOURCE = 'a' * 64


def spans(windows):
    return [(w['status'], w['start_frame'], w['end_frame']) for w in windows]


class MovementWindowPlanTests(unittest.TestCase):
    def test_windows_follow_confirmed_runs_and_tile_decoded_time(self):
        from aba_demo.movement_windows import decoded_seconds, plan_movement_windows

        data = candidate(SOURCE, uncertain={23})
        windows = plan_movement_windows(data)
        self.assertEqual(spans(windows), [
            ('eligible', 0, 11), ('eligible', 12, 22), ('identity_uncertain', 23, 23),
            ('eligible', 24, 41), ('eligible', 42, 59)])
        self.assertEqual([w['segment_id'] for w in windows],
                         [f'mov-{number:06d}' for number in range(5)])
        self.assertEqual(windows[0]['start_time'], 0.0)
        for previous, current in zip(windows, windows[1:]):
            self.assertEqual(previous['end_time'], current['start_time'])
        self.assertEqual(windows[-1]['end_time'], decoded_seconds(data))
        self.assertEqual(decoded_seconds(data), 6.0)
        uncertain = windows[2]
        self.assertEqual((uncertain['target_id'], uncertain['max_other_overlap'],
                          uncertain['frames']), (None, None, []))

    def test_a_non_sample_uncertain_frame_and_a_rebinding_split_windows(self):
        from aba_demo.movement_windows import plan_movement_windows

        for window in plan_movement_windows(candidate(SOURCE, uncertain={23})):
            if window['status'] == 'eligible':
                self.assertFalse(window['start_frame'] <= 23 <= window['end_frame'])
        switched = plan_movement_windows(candidate(SOURCE, switch_at=30))
        self.assertEqual(spans(switched), [('eligible', 0, 14), ('eligible', 15, 29),
                                           ('eligible', 30, 44), ('eligible', 45, 59)])
        self.assertEqual([w['target_id'] for w in switched], [7, 7, 9, 9])

    def test_short_runs_and_sparse_samples_are_not_eligible(self):
        from aba_demo.movement_windows import plan_movement_windows

        short = plan_movement_windows(candidate(SOURCE, decoded=20, uncertain=set(range(5, 15))))
        self.assertEqual(spans(short), [('too_short', 0, 4), ('identity_uncertain', 5, 14),
                                        ('too_short', 15, 19)])
        self.assertEqual((short[0]['target_id'], short[0]['frames']), (7, []))
        sparse = plan_movement_windows(candidate(SOURCE, decoded=12, sample_every=20))
        self.assertEqual(spans(sparse), [('insufficient_frames', 0, 11)])

    def test_frames_are_evenly_spaced_samples_with_target_box_and_overlap(self):
        from aba_demo.movement_windows import plan_movement_windows

        window = plan_movement_windows(candidate(SOURCE, decoded=20, sample_every=2))[0]
        self.assertEqual([f['frame_index'] for f in window['frames']], [0, 6, 12, 18])
        self.assertEqual([f['time'] for f in window['frames']], [0.0, 0.6, 1.2, 1.8])
        self.assertEqual(window['frames'][0]['target_box'], TARGET_BOX)
        # Intersection 0.1 x 0.7 over the smaller (target) area 0.3 x 0.7.
        self.assertAlmostEqual(window['max_other_overlap'], 1 / 3)
        two = plan_movement_windows(candidate(SOURCE, decoded=20, sample_every=2),
                                    frames_per_window=2)[0]
        self.assertEqual([f['frame_index'] for f in two['frames']], [0, 18])
        apart = plan_movement_windows(candidate(SOURCE, other_box=[0.6, 0.1, 0.9, 0.9]))[0]
        self.assertEqual(apart['max_other_overlap'], 0.0)
        self.assertNotIn(OTHER_BOX, [f['target_box'] for f in window['frames']])

    def test_frames_carry_every_other_tracked_person_box(self):
        from aba_demo.movement_windows import plan_movement_windows

        window = plan_movement_windows(candidate(SOURCE))[0]
        self.assertEqual([f['other_boxes'] for f in window['frames']],
                         [[OTHER_BOX]] * len(window['frames']))

    def test_window_parameters_are_bounded(self):
        from aba_demo.movement_windows import plan_movement_windows

        data = candidate(SOURCE)
        for options in ({'target_window_seconds': 0.2}, {'target_window_seconds': 9},
                        {'min_window_seconds': 1.5}, {'min_window_seconds': 0},
                        {'frames_per_window': 1}, {'frames_per_window': 5},
                        {'frames_per_window': True}):
            with self.subTest(options=options), \
                    self.assertRaisesRegex(ValueError, 'invalid_window_parameters'):
                plan_movement_windows(data, **options)


class TrackingCandidateLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'observations.pending.json'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')
        return self.path

    def test_loader_returns_exact_bytes_digest_for_a_passed_dense_candidate(self):
        from aba_demo.movement_windows import load_tracking_candidate

        data, digest = load_tracking_candidate(self.write(candidate(SOURCE)))
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(data['source']['decoded_frame_count'], 60)

    def test_loader_rejects_unpassed_sparse_misnumbered_or_unbound_candidates(self):
        from aba_demo.movement_windows import load_tracking_candidate

        base = candidate(SOURCE)
        sparse = copy.deepcopy(base)
        del sparse['provenance']['causal_audit'][7]
        shifted = copy.deepcopy(base)
        shifted['provenance']['causal_audit'][7]['time'] = 0.75
        foreign = copy.deepcopy(base)
        foreign['observations'][2]['target_id'] = 9
        no_target = copy.deepcopy(base)
        no_target['observations'][2]['boxes'] = no_target['observations'][2]['boxes'][1:]
        orphan = copy.deepcopy(base)
        orphan['observations'][2]['time'] = 1.05
        other_sha = copy.deepcopy(base)
        other_sha['provenance']['sha256'] = 'b' * 64
        bad_box = copy.deepcopy(base)
        bad_box['observations'][2]['boxes'][0]['xyxy'] = [0.5, 0.2, 0.4, 0.9]
        cases = [candidate(SOURCE, passed=False), sparse, shifted, foreign, no_target,
                 orphan, other_sha, bad_box, [], {**base, 'schema_version': 2},
                 {**base, 'mode': 'live'}]
        for value in cases:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_tracking_candidate'):
                load_tracking_candidate(self.write(value))
        self.path.write_bytes(b'\xff not json')
        with self.assertRaisesRegex(ValueError, 'invalid_tracking_candidate'):
            load_tracking_candidate(self.path)


if __name__ == '__main__':
    unittest.main()
