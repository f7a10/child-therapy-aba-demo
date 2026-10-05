"""Version 2 readings: lying, held posture, gap reasons, work area and motion bands."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from movement_fixtures import TARGET_BOX, candidate
from test_posture_reader import FakeReader, body


def skeleton(shoulder, hip, knee=None, *, confidence=0.9):
    """17 keypoints with only shoulders, hips and (optionally) knees seen, at (x, y) points."""
    points = [[0.0, 0.0, 0.0] for _ in range(17)]
    for indices, point in (((5, 6), shoulder), ((11, 12), hip), ((13, 14), knee)):
        if point is not None:
            for index in indices:
                points[index] = [point[0], point[1], confidence]
    return points


def sample(time, state, *, reason=None, hip=0.5, torso=0.2, identity='confirmed'):
    return {'time': time, 'identity': identity, 'state': state, 'reason': reason,
            'hip_y': hip, 'torso': torso}


class PostureFeatureTests(unittest.TestCase):
    def test_body_angles(self):
        from aba_demo.posture_features import body_measures

        upright = body_measures(skeleton((0.5, 0.3), (0.5, 0.5), (0.5, 0.7)), aspect=1.0)
        self.assertAlmostEqual(upright[0], 0.0)
        self.assertAlmostEqual(upright[1], 0.0)
        self.assertAlmostEqual(upright[2], 0.5)
        self.assertAlmostEqual(upright[3], 0.2)
        flat = body_measures(skeleton((0.3, 0.5), (0.5, 0.5)), aspect=1.0)
        self.assertAlmostEqual(flat[0], 90.0)
        self.assertIsNone(flat[1])  # no knee seen
        head_down = body_measures(skeleton((0.5, 0.7), (0.5, 0.5)), aspect=1.0)
        self.assertAlmostEqual(head_down[0], 180.0)
        self.assertEqual(body_measures(None, aspect=1.0), (None, None, None, None))

    def test_lying_needs_a_horizontal_body_and_legs_that_do_not_hang(self):
        from aba_demo.posture_features import classify_posture_v2

        self.assertEqual(classify_posture_v2(None, 85.0, 80.0), 'lying')
        self.assertEqual(classify_posture_v2(None, 90.0, None), 'not_measurable')  # thighs unseen
        self.assertEqual(classify_posture_v2(None, 85.0, 10.0), 'not_measurable')  # bent over, legs down
        self.assertEqual(classify_posture_v2(None, 160.0, None), 'not_measurable')  # head below hips
        self.assertEqual(classify_posture_v2(-0.2, 10.0, 80.0), 'sitting')
        self.assertEqual(classify_posture_v2(0.7, 5.0, 2.0), 'standing')

    def test_gap_reasons(self):
        from aba_demo.posture_features import gap_reason

        self.assertEqual(gap_reason(None), 'no_pose')
        self.assertEqual(gap_reason(skeleton(None, (0.5, 0.5))), 'torso_hidden')
        self.assertEqual(gap_reason(skeleton((0.3, 0.5), (0.5, 0.5))), 'bent_over')
        self.assertEqual(gap_reason(skeleton((0.5, 0.3), (0.5, 0.5))), 'knees_hidden')

    def test_held_posture_needs_a_stable_anchor_and_hips_that_stay(self):
        from aba_demo.posture_features import held_postures

        knees = dict(reason='knees_hidden')
        rows = [sample(0.0, 'sitting'), sample(0.2, 'sitting'), sample(0.4, 'sitting'),
                sample(0.6, 'not_measurable', **knees),                    # held
                sample(0.8, 'not_measurable', **knees, hip=0.40),          # hips rose 0.5 torso
                sample(1.0, 'not_measurable', **knees, hip=0.52),          # back down: held again
                sample(1.2, 'unclear'),                                    # knees seen, gray band
                sample(1.4, 'not_measurable', reason='torso_hidden', hip=None, torso=None)]
        self.assertEqual(held_postures(rows), [None, None, None, 'sitting', None, 'sitting', None, None])
        # Two agreeing samples are not enough.
        self.assertEqual(held_postures(rows[1:])[2:4], [None, None])

    def test_identity_gaps_lying_and_new_postures_drop_the_anchor(self):
        from aba_demo.posture_features import held_postures

        knees = dict(reason='knees_hidden')
        stable = [sample(0.0, 'sitting'), sample(0.2, 'sitting'), sample(0.4, 'sitting')]
        blip = stable + [sample(0.6, None, identity='uncertain'), sample(0.8, 'not_measurable', **knees)]
        self.assertEqual(held_postures(blip)[-1], 'sitting')  # a short blip keeps it
        long_gap = stable + [sample(t, None, identity='uncertain') for t in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6)]
        long_gap.append(sample(1.8, 'not_measurable', **knees))
        self.assertIsNone(held_postures(long_gap)[-1])
        lying = stable + [sample(0.6, 'lying'), sample(0.8, 'not_measurable', **knees)]
        self.assertIsNone(held_postures(lying)[-1])
        other = stable + [sample(0.6, 'standing'), sample(0.8, 'not_measurable', **knees)]
        self.assertIsNone(held_postures(other)[-1])

    def test_lying_events_and_held_samples_make_no_events(self):
        from aba_demo.posture_features import EVENT_KINDS_V2, posture_events

        rows = [{'time': round(i * 0.2, 1), 'identity': 'confirmed', 'state': state}
                for i, state in enumerate(['sitting'] * 3 + ['lying'] * 3 + ['standing'] * 3)]
        kinds = [e['kind'] for e in posture_events(rows, kinds=EVENT_KINDS_V2)]
        self.assertEqual(kinds, ['to_lying', 'from_lying'])
        # Without lying in the kinds (version 1), the same rows read sit_to_stand.
        self.assertEqual([e['kind'] for e in posture_events(rows)], ['sit_to_stand'])


class FakeKneeDetector:
    """Child sits with knees seen until frame 30, then the knees are hidden (same hips)."""

    def detect(self, image):
        index = image.info['frame_index']
        points = body(0.46, TARGET_BOX)
        if index >= 30:
            for knee in (13, 14):
                points[knee][2] = 0.1
        return [{'xyxy': list(TARGET_BOX), 'keypoints': points}]


class PostureReaderV2Tests(unittest.TestCase):
    def test_hidden_knees_after_a_stable_seat_are_held_and_validated(self):
        from aba_demo.posture_reader import read_posture
        from aba_demo.posture_schema import validate_posture_document

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'authorized.mp4'
            video.write_bytes(b'synthetic-source-not-video')
            source = hashlib.sha256(video.read_bytes()).hexdigest()
            tracking = root / 'observations.pending.json'
            tracking.write_text(json.dumps(candidate(source)), encoding='utf-8')
            report = read_posture(video, tracking, root / 'posture', detector=FakeKneeDetector(),
                                  frame_reader_factory=FakeReader)
            document = json.loads((root / 'posture' / 'posture.pending.json').read_text(encoding='utf-8'))
        self.assertEqual(document['schema_version'], 2)
        validate_posture_document(document, 6.1)
        samples = document['samples']
        self.assertEqual({s['state'] for s in samples[:6]}, {'sitting'})
        self.assertEqual({(s['state'], s['reason'], s['held']) for s in samples[6:]},
                         {('not_measurable', 'knees_hidden', 'sitting')})
        self.assertEqual(report['held_counts'], {'sitting': len(samples) - 6})
        self.assertEqual(document['events'], [])
        tampered = copy.deepcopy(document)
        tampered['samples'][7]['held'] = 'standing'
        with self.assertRaises(ValueError):
            validate_posture_document(tampered, 6.1)
        tampered = copy.deepcopy(document)
        tampered['samples'][7]['reason'] = None
        with self.assertRaises(ValueError):
            validate_posture_document(tampered, 6.1)


class WorkAreaTests(unittest.TestCase):
    def test_overlap_and_state(self):
        from aba_demo.orientation_features import area_overlap, area_state

        region = [0.5, 0.5, 1.0, 1.0]
        self.assertAlmostEqual(area_overlap([0.5, 0.5, 0.7, 0.7], region), 1.0)
        self.assertAlmostEqual(area_overlap([0.4, 0.5, 0.6, 0.7], region), 0.5)
        self.assertEqual(area_overlap([0.0, 0.0, 0.2, 0.2], region), 0.0)
        self.assertIsNone(area_overlap([0.3, 0.3, 0.2, 0.4], region))
        self.assertEqual(area_state(0.5, 0.001), 'at_area')
        self.assertEqual(area_state(0.05, 0.001), 'away_from_area')
        self.assertEqual(area_state(0.18, 0.001), 'unclear')
        self.assertEqual(area_state(0.5, None), 'not_measurable')
        self.assertEqual(area_state(0.5, 0.05), 'not_measurable')  # camera moving

    def test_leaving_and_returning_are_events_in_time_order(self):
        from aba_demo.orientation_features import orientation_events_v2

        areas = ['at_area'] * 3 + ['away_from_area'] * 3 + ['at_area'] * 3
        rows = [{'time': round(i * 0.2, 1), 'identity': 'confirmed', 'state': 'not_measurable',
                 'area_state': area} for i, area in enumerate(areas)]
        events = orientation_events_v2(rows)
        self.assertEqual([(e['kind'], e['start_time'], e['end_time']) for e in events],
                         [('left_work_area', 0.4, 0.6), ('returned_to_work_area', 1.0, 1.2)])

    def test_the_reader_writes_a_valid_work_area_reading(self):
        from aba_demo.orientation_reader import read_orientation
        from aba_demo.orientation_schema import validate_orientation_document
        from test_orientation_reader import FakeDetector, FakeMotion
        from test_orientation_reader import FakeReader as OrientationFrames

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'authorized.mp4'
            video.write_bytes(b'synthetic-source-not-video')
            source = hashlib.sha256(video.read_bytes()).hexdigest()
            tracking = root / 'observations.pending.json'
            tracking.write_text(json.dumps(candidate(source)), encoding='utf-8')
            # The camera pans right by 0.03 frame heights at frame 30, and has no estimate at frame 40.
            report = read_orientation(video, tracking, root / 'out', task_region=[0.0, 0.5, 0.5, 1.0],
                                      detector=FakeDetector(), motion_estimator=FakeMotion(moving={30}, lost={40}),
                                      frame_reader_factory=OrientationFrames)
            document = json.loads((root / 'out' / 'orientation.pending.json').read_text(encoding='utf-8'))
        self.assertEqual(document['schema_version'], 3)
        validate_orientation_document(document, 6.1)
        samples = document['samples']
        states = [s['area_state'] for s in samples]
        self.assertEqual(states[0], 'at_area')          # the region as drawn needs no camera step
        self.assertEqual(states[8], 'not_measurable')   # no camera estimate for this step
        self.assertIsNone(samples[8]['area_region'])
        self.assertEqual(set(states[:8] + states[9:]), {'at_area'})
        self.assertEqual(report['area_counts']['at_area'], len(states) - 1)
        # Each frame is matched to the drawing frame, so shifts do not add up: the fake
        # camera is 0.001 away from it except at frame 30 (0.03, x in frame-height units).
        drawn = samples[0]['area_region'][0]
        self.assertAlmostEqual((samples[5]['area_region'][0] - drawn) * 160 / 90, 0.001, places=4)
        self.assertAlmostEqual((samples[6]['area_region'][0] - drawn) * 160 / 90, 0.03, places=4)
        self.assertAlmostEqual((samples[7]['area_region'][0] - drawn) * 160 / 90, 0.001, places=4)
        tampered = copy.deepcopy(document)
        tampered['samples'][3]['area_state'] = 'away_from_area'
        with self.assertRaises(ValueError):
            validate_orientation_document(tampered, 6.1)

    def test_region_following_and_distance(self):
        from aba_demo.orientation_features import (area_gap, area_state_v3, follow_region,
                                                   region_in_frame)

        region = [0.2, 0.2, 0.4, 0.4]
        moved = follow_region(region, [1.0, 0.0, 0.1, 0.0, 1.0, -0.05], 2.0)
        self.assertEqual([round(v, 3) for v in moved], [0.25, 0.15, 0.45, 0.35])
        zoomed = follow_region(region, [1.1, 0.0, 0.0, 0.0, 1.1, 0.0], 1.0)
        self.assertEqual([round(v, 3) for v in zoomed], [0.22, 0.22, 0.44, 0.44])
        self.assertIsNone(follow_region(region, None, 1.0))
        self.assertIsNone(follow_region(region, [1.6, 0.0, 0.0, 0.0, 1.6, 0.0], 1.0))  # implausible zoom
        self.assertAlmostEqual(region_in_frame([0.8, 0.0, 1.2, 0.5]), 0.5)
        self.assertEqual(area_gap([0.1, 0.1, 0.3, 0.5], [0.2, 0.2, 0.6, 0.6]), 0.0)       # overlapping
        self.assertAlmostEqual(area_gap([0.0, 0.0, 0.1, 0.4], [0.3, 0.0, 0.5, 0.4]), 0.5)  # 0.2 away / 0.4 tall
        self.assertEqual(area_state_v3(0.0), 'at_area')
        self.assertEqual(area_state_v3(0.15), 'unclear')
        self.assertEqual(area_state_v3(0.5), 'away_from_area')
        self.assertEqual(area_state_v3(None), 'not_measurable')


class MotionAndSummaryTests(unittest.TestCase):
    def test_motion_states(self):
        from aba_demo.large_movement_features import motion_states

        still = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        rows = []
        for i in range(12):
            x = 0.2 if i < 6 else 0.2 + 0.1 * (i - 5)
            rows.append({'time': round(i * 0.2, 1), 'identity': 'confirmed', 'centre': [x, 0.5],
                         'torso': 0.1, 'camera': None if i == 0 else still})
        states = motion_states(rows)
        self.assertEqual(states[:3], [None, None, None])  # less than half a window seen
        self.assertEqual(set(states[3:6]), {'still'})
        self.assertEqual(states[-1], 'moving')

    def test_review_summary_shows_held_time_and_gap_reasons(self):
        from aba_demo.live.library import channel_summary

        base = {'leg_ratio': None, 'torso_angle': 5.0, 'thigh_angle': None, 'hip_y': 0.5, 'torso': 0.2}
        rows = [dict(base, time=0.0, identity='confirmed', state='sitting', reason=None, held=None),
                dict(base, time=0.2, identity='confirmed', state='not_measurable', reason='knees_hidden',
                     held='sitting'),
                dict(base, time=0.4, identity='confirmed', state='not_measurable', reason='knees_hidden',
                     held=None),
                dict(base, time=0.6, identity='uncertain', state=None, reason=None, held=None)]
        summary = channel_summary('posture', {'schema_version': 2, 'samples': rows}, 0.8)
        self.assertAlmostEqual(summary['coverage'], 0.25)
        self.assertAlmostEqual(summary['held'], 0.25)
        self.assertEqual(summary['bands'], [[0.0, 0.2, 'sitting'], [0.2, 0.4, 'held_sitting']])
        self.assertEqual(summary['gaps'], [[0.4, 0.6, 'knees_hidden'], [0.6, 0.8, 'identity']])
        self.assertEqual(summary['reasons'], {'identity': 0.25, 'knees_hidden': 0.25})
        area = channel_summary('orientation', {'schema_version': 2, 'samples': [
            {'time': 0.0, 'identity': 'confirmed', 'state': 'not_measurable', 'area_state': 'at_area'},
            {'time': 0.2, 'identity': 'confirmed', 'state': 'toward', 'area_state': 'not_measurable'}]}, 0.4)
        self.assertEqual(area['bands'], [[0.0, 0.2, 'at_area']])
        self.assertEqual(area['gaps'], [[0.2, 0.4, 'camera']])
        self.assertAlmostEqual(area['head_coverage'], 0.5)


if __name__ == '__main__':
    unittest.main()
