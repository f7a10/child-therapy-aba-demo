"""Pure posture features: leg ratio, provisional state, and stable transition events."""
import unittest


def keypoints(*, shoulder_y=0.30, hip_y=0.50, knee_y=0.62, confidence=0.9, knee_confidence=None):
    """17 COCO keypoints in normalized image coordinates; only torso and knees matter."""
    points = [[0.5, 0.1, 0.0] for _ in range(17)]
    for index in (5, 6):
        points[index] = [0.45 + 0.1 * (index - 5), shoulder_y, confidence]
    for index in (11, 12):
        points[index] = [0.45 + 0.1 * (index - 11), hip_y, confidence]
    for index in (13, 14):
        points[index] = [0.45 + 0.1 * (index - 13), knee_y,
                         confidence if knee_confidence is None else knee_confidence]
    return points


def sample(time, state, identity='confirmed'):
    return {'time': time, 'identity': identity, 'state': state}


class LegRatioTests(unittest.TestCase):
    def test_ratio_is_knee_drop_below_hips_over_torso_length(self):
        from aba_demo.posture_features import leg_ratio

        self.assertAlmostEqual(leg_ratio(keypoints()), 0.6)
        self.assertAlmostEqual(leg_ratio(keypoints(knee_y=0.44)), -0.3)

    def test_ratio_abstains_on_hidden_or_degenerate_joints(self):
        from aba_demo.posture_features import leg_ratio

        for points in (keypoints(knee_confidence=0.2), keypoints(confidence=0.3),
                       keypoints(shoulder_y=0.495), keypoints(shoulder_y=0.6), None,
                       keypoints()[:16], [[0.5, float('nan'), 0.9]] * 17):
            with self.subTest():
                self.assertIsNone(leg_ratio(points))


    def test_a_standing_reading_needs_both_knees_when_asked(self):
        from aba_demo.posture_features import leg_ratio

        one_knee = keypoints()
        one_knee[14][2] = 0.3  # the other knee hidden behind a table or an adult
        self.assertAlmostEqual(leg_ratio(one_knee), 0.6)  # rule off: unchanged
        self.assertIsNone(leg_ratio(one_knee, standing_needs_both_knees=True))
        self.assertAlmostEqual(leg_ratio(keypoints(), standing_needs_both_knees=True), 0.6)
        seated = keypoints(knee_y=0.44)
        seated[14][2] = 0.3
        self.assertAlmostEqual(leg_ratio(seated, standing_needs_both_knees=True), -0.3)


class PostureStateTests(unittest.TestCase):
    def test_states_have_a_gray_band_and_never_guess(self):
        from aba_demo.posture_features import classify_posture

        self.assertEqual(classify_posture(0.6), 'standing')
        self.assertEqual(classify_posture(0.40), 'standing')
        self.assertEqual(classify_posture(0.25), 'sitting')
        self.assertEqual(classify_posture(-0.3), 'sitting')
        self.assertEqual(classify_posture(0.3), 'unclear')
        self.assertEqual(classify_posture(None), 'not_measurable')
        self.assertEqual(classify_posture(0.3, standing_min=0.3, sitting_max=0.1), 'standing')
        with self.assertRaisesRegex(ValueError, 'invalid_posture_thresholds'):
            classify_posture(0.3, standing_min=0.2, sitting_max=0.3)


class PostureEventTests(unittest.TestCase):
    def series(self, states, start=0.0, step=0.2):
        return [sample(round(start + index * step, 3), state) for index, state in enumerate(states)]

    def test_a_stable_change_is_one_event_with_before_and_after_evidence(self):
        from aba_demo.posture_features import posture_events

        events = posture_events(self.series(['standing'] * 4 + ['unclear'] + ['sitting'] * 4))
        self.assertEqual(events, [{'kind': 'stand_to_sit', 'start_time': 0.6, 'end_time': 1.0,
                                   'evidence_times': [0.6, 1.0], 'detected_time': 1.4}])

    def test_flicker_identity_gaps_and_long_unmeasured_gaps_make_no_event(self):
        from aba_demo.posture_features import posture_events

        flicker = self.series(['sitting'] * 4 + ['standing'] * 2 + ['sitting'] * 4)
        self.assertEqual(posture_events(flicker), [])
        gap = self.series(['standing'] * 4) + [sample(0.8, None, 'uncertain')] + self.series(
            ['sitting'] * 4, start=1.0)
        self.assertEqual(posture_events(gap), [])
        unmeasured = self.series(['standing'] * 4 + ['not_measurable'] * 20 + ['sitting'] * 4)
        self.assertEqual(posture_events(unmeasured), [])
        self.assertEqual(len(posture_events(unmeasured, max_gap_seconds=5.0)), 1)

    def test_sit_to_stand_and_bounded_parameters(self):
        from aba_demo.posture_features import posture_events

        events = posture_events(self.series(['sitting'] * 3 + ['standing'] * 3))
        self.assertEqual([event['kind'] for event in events], ['sit_to_stand'])
        for options in ({'min_stable_samples': 1}, {'min_stable_samples': 50},
                        {'max_gap_seconds': 0}, {'max_gap_seconds': 61}):
            with self.subTest(options=options), \
                    self.assertRaisesRegex(ValueError, 'invalid_posture_parameters'):
                posture_events([], **options)


if __name__ == '__main__':
    unittest.main()
