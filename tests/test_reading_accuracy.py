"""Reading accuracy against labels, doctor verdict counts and recording hints."""
import json
import tempfile
import unittest
from pathlib import Path

from test_live_library import make_session
from test_session_measures import HS, N, S, T, posture_doc


class LabelAccuracyTests(unittest.TestCase):
    def test_measured_and_inferred_readings_are_scored_apart(self):
        from aba_demo.reading_accuracy import label_accuracy

        documents = {'posture': posture_doc([S, S, T, HS, N, S], step=1.0)}
        labels = {0.0: {'posture': 'sitting'}, 1.0: {'posture': 'standing'},   # measured right / wrong
                  2.0: {'posture': 'standing'}, 3.0: {'posture': 'sitting'},   # measured right, inferred right
                  4.0: {'posture': 'sitting'},                                  # missed
                  5.0: {'posture': 'not_visible'}}                              # a reading nobody could check
        result = label_accuracy(labels, documents)['posture']
        self.assertEqual(result['labeled'], 5)
        self.assertEqual(result['measured'], {'count': 3, 'correct': 2})
        self.assertEqual(result['inferred'], {'count': 1, 'correct': 1})
        self.assertEqual((result['missed'], result['not_visible'], result['unverifiable']), (1, 1, 1))
        self.assertEqual(result['confusion']['standing'], {'sitting': 1, 'standing': 1})
        self.assertNotIn('area', label_accuracy(labels, documents))

    def test_merge_and_points(self):
        from aba_demo.reading_accuracy import label_accuracy, label_points, merge_scores

        documents = {'posture': posture_doc([S, S], step=1.0)}
        one = label_accuracy({0.0: {'posture': 'sitting'}}, documents)
        total = merge_scores(merge_scores({}, one), one)
        self.assertEqual(total['posture']['measured'], {'count': 2, 'correct': 2})
        self.assertEqual(label_points(12.0), [5.0, 10.0])

    def test_verdicts_and_hints(self):
        from aba_demo.reading_accuracy import recording_hints, verdict_counts

        entries = [{'entry_id': 'a', 'channel': 'posture', 'kind': 'sit_to_stand', 'origin': 'measured'},
                   {'entry_id': 'b', 'channel': 'context', 'kind': 'context_note', 'origin': 'suggested'},
                   {'entry_id': 'c', 'channel': 'posture', 'kind': 'sit_to_stand', 'origin': 'measured'}]
        groups = [{'entry_ids': ['a', 'b']}, {'entry_ids': ['c']}]
        marks = {'a': {'verdict': 'confirmed'}, 'c': {'verdict': 'not_seen'}}
        self.assertEqual(verdict_counts(entries, groups, marks),
                         {'posture:sit_to_stand': {'confirmed': 1, 'not_seen': 1, 'unsure': 0}})
        hints = recording_hints({'posture': {'reasons': {'knees_hidden': 0.3, 'identity': 0.05}},
                                 'orientation': {'reasons': {'camera': 0.2}}})
        self.assertEqual(hints, ['knees_hidden', 'camera_moving'])


class LabelStoreTests(unittest.TestCase):
    def test_labels_over_http(self):
        from fastapi.testclient import TestClient

        from aba_demo.live.api import create_app
        from aba_demo.live.library import LABELS_NAME, SessionLibrary

        with tempfile.TemporaryDirectory() as directory:
            make_session(Path(directory) / 'one')
            library = SessionLibrary(directory)
            session_id = library.list()[0]['id']
            base = 'http://127.0.0.1:8767'
            with TestClient(create_app(port=8767, library=library), base_url=base) as client:
                state = client.get(f'/api/library/{session_id}/labels').json()
                self.assertEqual(state['interval'], 5.0)
                self.assertFalse(state['area'])
                point = state['points'][0] if state['points'] else None
                self.assertIsNone(point)  # the fixture is 2.2 s long: nothing to label yet
                self.assertEqual(client.put(f'/api/library/{session_id}/labels/1.0', json={'posture': 'sitting'},
                                            headers={'origin': base}).status_code, 400)
            with self.assertRaisesRegex(ValueError, 'invalid_label_time'):
                library.set_label(session_id, 5.0, 'sitting', None)
            self.assertFalse((Path(directory) / 'one' / LABELS_NAME).exists())
            overview = library.accuracy_overview()
            self.assertEqual((overview['sessions'], overview['labeled_sessions']), (1, 0))

    def test_labels_are_stored_and_scored(self):
        from aba_demo.live import library as module

        with tempfile.TemporaryDirectory() as directory:
            make_session(Path(directory) / 'one')
            library = module.SessionLibrary(directory)
            session_id = library.list()[0]['id']
            original = module.label_points
            module.label_points = lambda decoded, interval=1.0: [0.4, 1.6]  # points inside the fixture
            try:
                result = library.set_label(session_id, 0.4, 'standing', None)
                self.assertEqual(result['labels'], {'0.4': {'posture': 'standing', 'area': None}})
                self.assertEqual(result['accuracy']['posture']['labeled'], 1)
                with self.assertRaisesRegex(ValueError, 'no_work_area'):
                    library.set_label(session_id, 1.6, None, 'at_area')
                stored = json.loads((Path(directory) / 'one' / module.LABELS_NAME).read_text(encoding='utf-8'))
                self.assertEqual(stored['kind'], 'ground_truth_labels')
                self.assertEqual(library.accuracy_overview()['labeled_sessions'], 1)
                cleared = library.set_label(session_id, 0.4, None, None)
                self.assertEqual(cleared['labels'], {})
            finally:
                module.label_points = original


if __name__ == '__main__':
    unittest.main()
