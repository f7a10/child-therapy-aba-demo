"""Pure orientation features: head facing vs task region, states, stable events."""
import unittest

REGION_RIGHT = [0.7, 0.2, 0.9, 0.4]
REGION_LEFT = [0.1, 0.2, 0.3, 0.4]


def head(*, nose=(0.56, 0.30), ears=((0.50, 0.30), (0.50, 0.30)), ear_confidence=0.9,
         nose_confidence=0.9, shoulders=((0.45, 0.45), (0.55, 0.45)), shoulder_confidence=0.9):
    """17 COCO keypoints; only nose, ears and shoulders are set."""
    points = [[0.5, 0.5, 0.0] for _ in range(17)]
    points[0] = [nose[0], nose[1], nose_confidence]
    for index, ear in zip((3, 4), ears):
        points[index] = [ear[0], ear[1], ear_confidence]
    for index, shoulder in zip((5, 6), shoulders):
        points[index] = [shoulder[0], shoulder[1], shoulder_confidence]
    return points


def sample(time, state, identity='confirmed'):
    return {'time': time, 'identity': identity, 'state': state}


class FacingMeasureTests(unittest.TestCase):
    def test_angle_between_facing_and_region_direction(self):
        from aba_demo.orientation_features import facing_measure

        angle, length = facing_measure(head(), REGION_RIGHT)
        self.assertAlmostEqual(angle, 0.0, places=6)
        self.assertAlmostEqual(length, 0.06 / 0.15, places=6)
        angle, _ = facing_measure(head(), REGION_LEFT)
        self.assertAlmostEqual(angle, 180.0, places=6)
        angle, _ = facing_measure(head(nose=(0.50, 0.36)), REGION_RIGHT)
        self.assertAlmostEqual(angle, 90.0, places=6)

    def test_one_visible_ear_is_the_head_centre(self):
        from aba_demo.orientation_features import facing_measure

        points = head(ears=((0.50, 0.30), (0.9, 0.9)))
        points[4][2] = 0.1
        angle, _ = facing_measure(points, REGION_RIGHT)
        self.assertAlmostEqual(angle, 0.0, places=6)

    def test_image_aspect_is_respected(self):
        from aba_demo.orientation_features import facing_measure

        # Nose up-right at 45 degrees in normalized units; region straight right.
        points = head(nose=(0.56, 0.24))
        square, _ = facing_measure(points, [0.7, 0.2, 0.9, 0.4], aspect=1.0)
        wide, _ = facing_measure(points, [0.7, 0.2, 0.9, 0.4], aspect=16 / 9)
        self.assertGreater(square, wide)

    def test_abstains_without_nose_ear_shoulder_or_with_head_inside_region(self):
        from aba_demo.orientation_features import facing_measure

        no_ears = head()
        no_ears[3][2] = no_ears[4][2] = 0.2
        cases = [head(nose_confidence=0.2), no_ears, head(shoulder_confidence=0.1),
                 head(shoulders=((0.5, 0.3), (0.5, 0.3))), None, head()[:16],
                 [[0.5, float('nan'), 0.9]] * 17]
        for points in cases:
            with self.subTest():
                self.assertEqual(facing_measure(points, REGION_RIGHT), (None, None))
        self.assertEqual(facing_measure(head(), [0.4, 0.2, 0.6, 0.4]), (None, None))

    def test_task_region_is_validated(self):
        from aba_demo.orientation_features import valid_task_region

        self.assertTrue(valid_task_region([0.1, 0.2, 0.5, 0.6]))
        for region in ([0.5, 0.2, 0.1, 0.6], [0, 0, 1.2, 1], [0.1, 0.1, 0.105, 0.5],
                       [0.1, 0.2, 0.5], 'x', [0.1, float('nan'), 0.5, 0.6], [0, 0, True, 1]):
            with self.subTest(region=region):
                self.assertFalse(valid_task_region(region))


class OrientationStateTests(unittest.TestCase):
    def test_states_have_a_gray_band_and_a_short_vector_is_unclear(self):
        from aba_demo.orientation_features import classify_orientation

        self.assertEqual(classify_orientation(10.0, 0.8), 'toward')
        self.assertEqual(classify_orientation(60.0, 0.8), 'toward')
        self.assertEqual(classify_orientation(80.0, 0.8), 'unclear')
        self.assertEqual(classify_orientation(120.0, 0.8), 'away')
        self.assertEqual(classify_orientation(170.0, 0.1), 'unclear')
        self.assertEqual(classify_orientation(None, None), 'not_measurable')
        self.assertEqual(classify_orientation(70.0, 0.8, toward_max=75.0, away_min=110.0),
                         'toward')
        with self.assertRaisesRegex(ValueError, 'invalid_orientation_thresholds'):
            classify_orientation(30.0, 0.8, toward_max=120.0, away_min=100.0)


class OrientationGateTests(unittest.TestCase):
    def test_only_a_seated_child_under_a_still_camera_has_an_orientation(self):
        from aba_demo.orientation_features import orientation_state

        self.assertEqual(orientation_state(10.0, 0.8, True, 0.0), 'toward')
        self.assertEqual(orientation_state(150.0, 0.8, True, 0.015), 'away')
        self.assertEqual(orientation_state(80.0, 0.8, True, 0.01), 'unclear')
        for seated, shift in ((False, 0.0), (True, 0.016), (True, None), (True, -0.001)):
            with self.subTest(seated=seated, shift=shift):
                self.assertEqual(orientation_state(10.0, 0.8, seated, shift),
                                 'not_measurable')
        self.assertEqual(orientation_state(None, None, True, 0.0), 'not_measurable')
        self.assertEqual(orientation_state(10.0, 0.8, True, 0.05, max_camera_shift=0.1),
                         'toward')
        with self.assertRaisesRegex(ValueError, 'invalid_orientation_thresholds'):
            orientation_state(10.0, 0.8, True, 0.0, max_camera_shift=-1.0)


class StableSeatedTests(unittest.TestCase):
    def rows(self, ratios, start=0.0, step=0.2):
        return [{'time': round(start + index * step, 3), 'identity': 'confirmed',
                 'leg_ratio': ratio} for index, ratio in enumerate(ratios)]

    def test_seated_after_three_sitting_samples_until_standing_is_confirmed(self):
        from aba_demo.orientation_features import stable_seated

        sit, stand, unclear = -0.2, 0.6, 0.3
        self.assertEqual(stable_seated(self.rows([sit, sit, sit])), [False, False, True])
        # Hidden knees or an unclear posture neither confirm nor break the seat.
        self.assertEqual(stable_seated(self.rows([sit, sit, sit, None, unclear, stand, stand,
                                                  sit, stand, stand, stand])),
                         [False, False, True, True, True, True, True, True, True, True, False])
        self.assertEqual(stable_seated(self.rows([sit, None, sit, unclear, sit])),
                         [False, False, False, False, True])
        self.assertEqual(stable_seated(self.rows([stand] * 3 + [sit] * 3)),
                         [False] * 5 + [True])

    def test_identity_gaps_and_long_unmeasured_gaps_forget_the_seat(self):
        from aba_demo.orientation_features import stable_seated

        rows = self.rows([-0.2] * 3) + [
            {'time': 0.6, 'identity': 'uncertain', 'leg_ratio': None}] + self.rows(
            [-0.2] * 3, start=0.8)
        self.assertEqual(stable_seated(rows), [False, False, True, False, False, False, True])
        unmeasured = self.rows([-0.2] * 3 + [None] * 20)
        seated = stable_seated(unmeasured)
        self.assertTrue(seated[17])          # 3.0 s after the last sitting sample
        self.assertFalse(seated[18])         # 3.2 s: forgotten
        self.assertFalse(any(seated[18:]))
        self.assertTrue(stable_seated(unmeasured, max_gap_seconds=5.0)[18])

    def test_causal_and_bounded(self):
        from aba_demo.orientation_features import stable_seated

        rows = self.rows([-0.2, -0.2, -0.2, 0.6, 0.6, 0.6, None, -0.2])
        full = stable_seated(rows)
        for end in range(1, len(rows) + 1):
            self.assertEqual(stable_seated(rows[:end]), full[:end])
        for options in ({'min_stable_samples': 1}, {'max_gap_seconds': 0},
                        {'standing_min': 0.2, 'sitting_max': 0.3}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                stable_seated(rows, **options)

    def test_camera_shift_is_the_translation_of_the_estimated_step(self):
        from aba_demo.orientation_features import camera_shift

        self.assertAlmostEqual(camera_shift([1.0, 0.0, 0.003, 0.0, 1.0, 0.004]), 0.005)
        self.assertIsNone(camera_shift(None))
        self.assertIsNone(camera_shift([1.0, 0.0, float('nan'), 0.0, 1.0, 0.0]))
        self.assertIsNone(camera_shift([1.0, 0.0, 0.0]))


class OrientationEventTests(unittest.TestCase):
    def series(self, states, start=0.0, step=0.2):
        return [sample(round(start + index * step, 3), state) for index, state in enumerate(states)]

    def test_a_stable_turn_is_one_event_with_before_and_after_evidence(self):
        from aba_demo.orientation_features import orientation_events

        events = orientation_events(self.series(['toward'] * 4 + ['unclear'] + ['away'] * 4))
        self.assertEqual(events, [{'kind': 'turned_away_from_task', 'start_time': 0.6,
                                   'end_time': 1.0, 'evidence_times': [0.6, 1.0],
                                   'detected_time': 1.4}])
        back = orientation_events(self.series(['away'] * 3 + ['toward'] * 3))
        self.assertEqual([event['kind'] for event in back], ['turned_back_to_task'])

    def test_flicker_identity_gaps_and_long_unmeasured_gaps_make_no_event(self):
        from aba_demo.orientation_features import orientation_events

        flicker = self.series(['toward'] * 4 + ['away'] * 2 + ['toward'] * 4)
        self.assertEqual(orientation_events(flicker), [])
        gap = self.series(['toward'] * 4) + [sample(0.8, None, 'uncertain')] + self.series(
            ['away'] * 4, start=1.0)
        self.assertEqual(orientation_events(gap), [])
        unmeasured = self.series(['toward'] * 4 + ['not_measurable'] * 20 + ['away'] * 4)
        self.assertEqual(orientation_events(unmeasured), [])
        self.assertEqual(len(orientation_events(unmeasured, max_gap_seconds=5.0)), 1)

    def test_bounded_parameters(self):
        from aba_demo.orientation_features import orientation_events

        for options in ({'min_stable_samples': 1}, {'min_stable_samples': 50},
                        {'max_gap_seconds': 0}, {'max_gap_seconds': 61}):
            with self.subTest(options=options), \
                    self.assertRaisesRegex(ValueError, 'invalid_orientation_parameters'):
                orientation_events([], **options)


if __name__ == '__main__':
    unittest.main()
