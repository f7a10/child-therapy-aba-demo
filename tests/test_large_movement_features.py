"""Pure large-movement features: body centre, camera compensation and episodes."""
import unittest

IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def keypoints(*, x=0.5, shoulder_y=0.30, hip_y=0.50, confidence=0.9, hip_confidence=None):
    """17 COCO keypoints in normalized image coordinates; only shoulders and hips matter."""
    points = [[0.5, 0.1, 0.0] for _ in range(17)]
    for index in (5, 6):
        points[index] = [x - 0.05 + 0.1 * (index - 5), shoulder_y, confidence]
    for index in (11, 12):
        points[index] = [x - 0.05 + 0.1 * (index - 11), hip_y,
                         confidence if hip_confidence is None else hip_confidence]
    return points


def sample(time, x, *, y=0.5, torso=0.2, camera=IDENTITY, identity='confirmed'):
    if identity != 'confirmed':
        return {'time': time, 'identity': identity, 'centre': None, 'torso': None,
                'camera': None}
    if x is None:
        return {'time': time, 'identity': 'confirmed', 'centre': None, 'torso': None,
                'camera': None}
    return {'time': time, 'identity': 'confirmed', 'centre': [x, y], 'torso': torso,
            'camera': None if camera is None else list(camera)}


def track(xs, *, step=0.2, start=0.0):
    """Samples every ``step`` seconds; the first one starts the segment (no camera)."""
    rows = []
    for number, x in enumerate(xs):
        time = round(start + number * step, 3)
        rows.append(sample(time, x, camera=None if number == 0 else IDENTITY))
    return rows


def events(rows, **options):
    from aba_demo.large_movement_features import large_movement_events
    return large_movement_events(rows, **options)


class BodyCentreTests(unittest.TestCase):
    def test_centre_is_hip_midpoint_and_scale_is_torso_length_in_height_units(self):
        from aba_demo.large_movement_features import body_centre

        measured = body_centre(keypoints(), aspect=2.0)
        self.assertAlmostEqual(measured['centre'][0], 1.0)
        self.assertAlmostEqual(measured['centre'][1], 0.5)
        self.assertAlmostEqual(measured['torso'], 0.2)
        tilted = body_centre(keypoints(x=0.5, shoulder_y=0.5, hip_y=0.5), aspect=1.0)
        self.assertIsNone(tilted)

    def test_centre_abstains_on_hidden_or_degenerate_joints(self):
        from aba_demo.large_movement_features import body_centre

        for points in (keypoints(hip_confidence=0.2), keypoints(confidence=0.3),
                       keypoints(shoulder_y=0.495), None, keypoints()[:16],
                       [[0.5, float('nan'), 0.9]] * 17):
            with self.subTest():
                self.assertIsNone(body_centre(points, aspect=1.0))
        with self.assertRaisesRegex(ValueError, 'invalid_aspect'):
            body_centre(keypoints(), aspect=0)


class CameraTests(unittest.TestCase):
    def test_camera_bounds(self):
        from aba_demo.large_movement_features import valid_camera

        self.assertTrue(valid_camera(IDENTITY))
        self.assertTrue(valid_camera([1.02, 0.0, 0.01, 0.0, 1.02, -0.008]))
        self.assertTrue(valid_camera([1.0, 0.0, 0.05, 0.0, 1.0, 0.0], max_shift=0.1))
        for matrix in ([1.0, 0.0, 0.02, 0.0, 1.0, 0.0], [1.0, 0.0, 0.0, 0.0, 1.0, -0.016],
                       [1.0, 0.0, 0.2, 0.0, 1.0, 0.0], [1.3, 0.0, 0.0, 0.0, 1.3, 0.0],
                       [1.0, 0.0, float('nan'), 0.0, 1.0, 0.0], [1.0] * 5, None):
            with self.subTest():
                self.assertFalse(valid_camera(matrix))


class EpisodeTests(unittest.TestCase):
    def test_still_child_with_jitter_has_no_event(self):
        self.assertEqual(events(track([0.5, 0.52, 0.49, 0.51, 0.5, 0.53, 0.5] * 5)), [])

    def test_fast_displacement_is_one_episode_detected_after_it_ends(self):
        xs = [0.5] * 5 + [0.6, 0.75, 0.9, 1.0] + [1.0] * 15
        found = events(track(xs))
        self.assertEqual(len(found), 1)
        event = found[0]
        self.assertEqual(event['kind'], 'large_movement')
        self.assertEqual((event['start_time'], event['end_time']), (0.8, 1.6))
        self.assertGreater(event['detected_time'], event['end_time'] + 2.0)
        self.assertEqual(event['evidence_times'][0], 0.8)
        self.assertEqual(event['evidence_times'][-1], 1.6)
        self.assertLessEqual(len(event['evidence_times']), 8)
        self.assertEqual(event['evidence_times'], sorted(event['evidence_times']))

    def test_slow_drift_is_not_a_large_movement(self):
        xs = [0.5 + 0.01 * number for number in range(60)]
        self.assertEqual(events(track(xs)), [])

    def test_small_camera_drift_is_removed(self):
        rows = track([0.5 + 0.012 * number for number in range(40)])
        for row in rows[1:]:
            row['camera'] = [1.0, 0.0, 0.012, 0.0, 1.0, 0.0]
        self.assertEqual(events(rows), [])
        still = track([0.5] * 20)
        for row in still:
            row['torso'] = 0.1
        for row in still[1:]:
            row['camera'] = [1.0, 0.0, -0.014, 0.0, 1.0, 0.0]
        self.assertEqual(len(events(still)), 1)

    def test_vertical_displacement_alone_is_not_a_large_movement(self):
        rows = [sample(round(number * 0.2, 3), 0.5, y=0.5 if number < 5 else 0.9,
                       camera=None if number == 0 else IDENTITY) for number in range(20)]
        self.assertEqual(events(rows), [])
        diagonal = [sample(round(number * 0.2, 3), 0.5 if number < 5 else 0.65,
                           y=0.5 if number < 5 else 0.9,
                           camera=None if number == 0 else IDENTITY) for number in range(20)]
        self.assertEqual(events(diagonal), [])

    def test_no_event_across_identity_gaps_or_segment_starts(self):
        xs = [0.5] * 5 + [0.6, 0.65] + [0.8, 0.9] + [0.9] * 5
        uncertain = track(xs)
        uncertain[7] = sample(uncertain[7]['time'], None, identity='uncertain')
        uncertain[8]['camera'] = None
        self.assertEqual(events(uncertain), [])
        restarted = track(xs)
        restarted[7]['camera'] = None
        self.assertEqual(events(restarted), [])

    def test_not_measurable_samples_neither_break_nor_fake_motion(self):
        xs = [0.5] * 5 + [None, 0.75, 0.9, 1.0] + [1.0] * 15
        found = events(track(xs))
        self.assertEqual([(e['start_time'], e['end_time']) for e in found], [(0.8, 1.6)])
        self.assertNotIn(1.0, found[0]['evidence_times'])

    def test_separate_movements_are_separate_and_overlapping_ones_merge(self):
        xs = [0.5] * 5 + [0.65, 0.8] + [0.8] * 20 + [0.65, 0.5] + [0.5] * 15
        self.assertEqual(len(events(track(xs))), 2)
        back_and_forth = [0.5] * 5 + [0.65, 0.8, 0.8, 0.65, 0.5, 0.65, 0.8] + [0.8] * 15
        self.assertEqual(len(events(track(back_and_forth))), 1)

    def test_movement_split_only_by_a_camera_break_stays_one_episode(self):
        xs = [0.5] * 5 + [0.65, 0.8, 0.95] + [0.95] * 12 + [1.1, 1.25, 1.4] + [1.4] * 15
        pause = range(8, 20)
        broken = track(xs)
        for index in pause:  # camera moving: every step rejected, nothing measured
            broken[index]['camera'] = None
        found = events(broken)
        self.assertEqual([(e['start_time'], e['end_time']) for e in found], [(0.8, 4.4)])
        # A measured pause is a real stop: two episodes.
        self.assertEqual(len(events(track(xs))), 2)
        # Measured stillness right after the first half: the break does not bridge it.
        late = track(xs)
        for index in range(14, 20):
            late[index]['camera'] = None
        self.assertEqual(len(events(late)), 2)
        identity_gap = track(xs)
        for index in pause:
            identity_gap[index] = sample(identity_gap[index]['time'], None, identity='uncertain')
        identity_gap[20]['camera'] = None
        self.assertEqual(len(events(identity_gap)), 2)  # never across identity gaps

    def test_open_episode_closes_at_the_last_sample_or_break(self):
        found = events(track([0.5] * 5 + [0.65, 0.8]))
        self.assertEqual([(e['end_time'], e['detected_time']) for e in found], [(1.2, 1.2)])
        rows = track([0.5] * 5 + [0.65, 0.8, 0.8])
        rows[7] = sample(rows[7]['time'], None, identity='uncertain')
        self.assertEqual([e['detected_time'] for e in events(rows)], [1.4])

    def test_inconsistent_camera_links_and_bad_parameters_are_rejected(self):
        rows = track([0.5, 0.5])
        rows[0]['camera'] = list(IDENTITY)
        with self.assertRaisesRegex(ValueError, 'inconsistent_large_movement_samples'):
            events(rows)
        gap = track([0.5, 0.5]) + [sample(3.0, 0.5)]
        with self.assertRaisesRegex(ValueError, 'inconsistent_large_movement_samples'):
            events(gap)
        for options in ({'displacement_threshold': 0}, {'window_seconds': 0},
                        {'max_gap_seconds': 100}):
            with self.subTest(options), self.assertRaisesRegex(
                    ValueError, 'invalid_large_movement_parameters'):
                events(track([0.5]), **options)

    def test_states_mark_segment_starts_and_unmeasurable_samples(self):
        from aba_demo.large_movement_features import sample_states

        rows = track([0.5, None, 0.5]) + [sample(0.6, None, identity='uncertain')]
        self.assertEqual(sample_states(rows),
                         ['segment_start', 'not_measurable', 'measured', None])


if __name__ == '__main__':
    unittest.main()
