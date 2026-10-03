"""Unified session timeline: measured channel events + therapist-set activity + highlight rules."""
import copy
import json
import unittest

from test_posture_schema import document as posture_document

POSTURE_SHA = 'c' * 64


def two_events():
    """Posture document with stand_to_sit (0.4-0.8) and sit_to_stand (1.4-2.0)."""
    from aba_demo.posture_features import classify_posture, posture_events

    ratios = [0.6, 0.6, 0.6, -0.3, -0.3, -0.3, -0.3, 0.6, 0.6, 0.6, 0.6]
    samples = [{'time': round(index * 0.2, 3), 'frame_index': index * 6, 'identity': 'confirmed',
                'state': classify_posture(ratio), 'leg_ratio': ratio}
               for index, ratio in enumerate(ratios)]
    events = [{'event_id': f'pos-{number:06d}', **event, 'clinician_confirmation': 'pending'}
              for number, event in enumerate(posture_events(samples))]
    return posture_document(samples=samples, events=events, decoded_seconds=2.2)


class TimelineBuildTests(unittest.TestCase):
    def test_leaving_the_seat_is_flagged_only_during_table_activity(self):
        from aba_demo.session_timeline import build_timeline

        posture = two_events()
        table = build_timeline({'posture': (posture, POSTURE_SHA)}, [{'start_time': 0.0, 'end_time': 2.2,
                                                       'activity': 'table'}], 2.5)
        self.assertEqual([(e['kind'], e['activity'], e['level']) for e in table['entries']],
                         [('stand_to_sit', 'table', 'info'), ('sit_to_stand', 'table', 'flag')])
        moving = build_timeline({'posture': (posture, POSTURE_SHA)}, [
            {'start_time': 0.0, 'end_time': 1.0, 'activity': 'table'},
            {'start_time': 1.0, 'end_time': 2.2, 'activity': 'movement'}], 2.5)
        self.assertEqual([(e['activity'], e['level']) for e in moving['entries']],
                         [('table', 'info'), ('movement', 'info')])
        entry = table['entries'][1]
        self.assertEqual((entry['channel'], entry['source_event_id'], entry['evidence_times']),
                         ('posture', 'pos-000001', posture['events'][1]['evidence_times']))
        self.assertEqual(entry['detected_time'], posture['events'][1]['detected_time'])
        self.assertEqual((entry['clinician_confirmation'], entry['origin']), ('pending', 'measured'))
        self.assertEqual(entry['entry_id'], 'tl-posture-pos-000001')
        self.assertEqual(table['channels'], {'posture': POSTURE_SHA})
        self.assertEqual(table['source_sha256'], posture['source_sha256'])

    def test_activity_segments_must_tile_the_session_with_known_activities(self):
        from aba_demo.session_timeline import build_timeline

        posture = two_events()
        cases = [
            [],
            [{'start_time': 0.0, 'end_time': 1.0, 'activity': 'table'}],
            [{'start_time': 0.0, 'end_time': 1.0, 'activity': 'table'},
             {'start_time': 1.2, 'end_time': 2.2, 'activity': 'break'}],
            [{'start_time': 0.0, 'end_time': 2.2, 'activity': 'tantrum'}],
            [{'start_time': 0.0, 'end_time': 2.2, 'activity': 'table', 'note': 'x'}],
            [{'start_time': 0.5, 'end_time': 2.2, 'activity': 'table'}],
        ]
        for segments in cases:
            with self.subTest(segments=segments), \
                    self.assertRaisesRegex(ValueError, 'invalid_activity_segments'):
                build_timeline({'posture': (posture, POSTURE_SHA)}, segments, 2.5)
        for channels in ({}, {'emotion': (posture, POSTURE_SHA)}, {'posture': (posture, 'x')},
                         {'posture': posture}):
            with self.subTest(channels=list(channels)),                     self.assertRaisesRegex(ValueError, 'invalid_channels'):
                build_timeline(channels, [{'start_time': 0.0, 'end_time': 2.2,
                                           'activity': 'table'}], 2.5)
        with self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
            build_timeline({'posture': ({**posture, 'events': []}, POSTURE_SHA)},
                           [{'start_time': 0.0, 'end_time': 2.2, 'activity': 'table'}], 2.5)


    def test_channels_are_merged_in_time_order_and_must_share_one_binding(self):
        from aba_demo.session_timeline import build_timeline
        from test_orientation_schema import document as orientation_document

        segments = [{'start_time': 0.0, 'end_time': 2.0, 'activity': 'table'}]
        both = build_timeline({'posture': (posture_document(), POSTURE_SHA),
                               'orientation': (orientation_document(), 'e' * 64)}, segments, 2.5)
        self.assertEqual([e['entry_id'] for e in both['entries']],
                         ['tl-orientation-ori-000000', 'tl-posture-pos-000000'])
        self.assertEqual(both['channels'], {'orientation': 'e' * 64, 'posture': POSTURE_SHA})
        self.assertTrue(all(e['level'] == 'info' for e in both['entries']))
        for other in (orientation_document(decoded_seconds=1.9),
                      orientation_document(source_sha256='f' * 64)):
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_channels'):
                build_timeline({'posture': (posture_document(), POSTURE_SHA),
                                'orientation': (other, 'e' * 64)}, segments, 2.5)

    def test_entries_that_happen_together_form_one_group(self):
        from aba_demo.session_timeline import build_timeline
        from test_large_movement_schema import document as movement_document
        from test_orientation_schema import document as orientation_document

        segments = [{'start_time': 0.0, 'end_time': 2.0, 'activity': 'table'}]
        timeline = build_timeline({'posture': (posture_document(), POSTURE_SHA),
                                   'orientation': (orientation_document(), 'e' * 64),
                                   'movement': (movement_document(), 'f' * 64)}, segments, 2.5)
        self.assertEqual(timeline['schema_version'], 3)
        self.assertEqual(len(timeline['groups']), 1)
        group = timeline['groups'][0]
        self.assertEqual(group['group_id'], 'grp-000000')
        self.assertEqual(sorted(group['entry_ids']), sorted(e['entry_id'] for e in timeline['entries']))
        self.assertEqual((group['start_time'], group['end_time']), (0.2, 0.8))
        self.assertEqual(group['detected_time'], max(e['detected_time'] for e in timeline['entries']))
        self.assertEqual(group['level'], 'info')
        flagged = build_timeline({'posture': (two_events(), POSTURE_SHA)},
                                 [{'start_time': 0.0, 'end_time': 2.2, 'activity': 'table'}], 2.5)
        self.assertEqual([g['level'] for g in flagged['groups']], ['flag'])

class TimelineVerifyTests(unittest.TestCase):
    def test_a_saved_timeline_must_match_its_channels_exactly(self):
        from aba_demo.session_timeline import build_timeline, encode_timeline, verify_timeline

        posture = two_events()
        segments = [{'start_time': 0.0, 'end_time': 2.2, 'activity': 'table'}]
        timeline = build_timeline({'posture': (posture, POSTURE_SHA)}, segments, 2.5)
        encoded = encode_timeline(timeline)
        self.assertEqual(json.loads(encoded), timeline)
        self.assertTrue(verify_timeline(json.loads(encoded), {'posture': (posture, POSTURE_SHA)}, 2.5))
        tampered = copy.deepcopy(timeline)
        tampered['entries'][1]['level'] = 'info'
        relabeled = copy.deepcopy(timeline)
        relabeled['activity_segments'][0]['activity'] = 'movement'
        other_sha = copy.deepcopy(timeline)
        other_sha['channels']['posture'] = 'd' * 64
        for value in (tampered, relabeled, other_sha):
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_session_timeline'):
                verify_timeline(value, {'posture': (posture, POSTURE_SHA)}, 2.5)


class TimelineScriptTests(unittest.TestCase):
    def test_script_builds_a_bound_timeline_from_activity_changes(self):
        import contextlib
        import hashlib
        import importlib.util
        import io
        import tempfile
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            'build_session_timeline', root / 'scripts' / 'build_session_timeline.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            posture_path = folder / 'posture.pending.json'
            raw = json.dumps(two_events()).encode('utf-8')
            posture_path.write_bytes(raw)
            output = folder / 'timeline.json'
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                code = script.main(['--posture', str(posture_path), '--output', str(output),
                                    '--activity', '0:table', '--activity', '1.0:movement'])
            self.assertEqual(code, 0)
            timeline = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(timeline['channels']['posture'], hashlib.sha256(raw).hexdigest())
            self.assertEqual([s['activity'] for s in timeline['activity_segments']],
                             ['table', 'movement'])
            self.assertIn('FLAGS 0', printed.getvalue())
            with self.assertRaisesRegex(ValueError, 'output_inside_repository'):
                script.main(['--posture', str(posture_path), '--output',
                             str(root / 'tests' / 'timeline-must-not-exist.json'),
                             '--activity', '0:table'])
            with self.assertRaisesRegex(ValueError, 'invalid_activity_segments'):
                script.main(['--posture', str(posture_path), '--output', str(folder / 'x.json'),
                             '--activity', '0.5:table'])


    def test_script_adds_optional_channels(self):
        import contextlib
        import importlib.util
        import io
        import tempfile
        from pathlib import Path
        from test_large_movement_schema import document as movement_document
        from test_context_channel_schema import document as context_document
        from test_orientation_schema import document as orientation_document

        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            'build_session_timeline', root / 'scripts' / 'build_session_timeline.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            paths = {}
            for name, value in (('posture', posture_document()),
                                ('orientation', orientation_document()),
                                ('movement', movement_document()),
                                ('context', context_document())):
                paths[name] = folder / f'{name}.json'
                paths[name].write_text(json.dumps(value), encoding='utf-8')
            output = folder / 'timeline.json'
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                script.main(['--posture', str(paths['posture']),
                             '--orientation', str(paths['orientation']),
                             '--movement', str(paths['movement']),
                             '--context', str(paths['context']),
                             '--output', str(output), '--activity', '0:table'])
            timeline = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(sorted(timeline['channels']),
                             ['context', 'movement', 'orientation', 'posture'])
            self.assertEqual([e['channel'] for e in timeline['entries']],
                             ['movement', 'context', 'orientation', 'posture'])
            self.assertIn('ملاحظة سياق (مقترح)', printed.getvalue())
            self.assertIn('حركة كبيرة', printed.getvalue())
            self.assertIn('التفت بعيداً عن المهمة', printed.getvalue())

if __name__ == '__main__':
    unittest.main()
