"""Session measures: episodes, summary, interval sheet and CSV export."""
import tempfile
import unittest
from pathlib import Path

from test_live_library import make_session


def posture_doc(states, step=0.5):
    """A posture reading from (state, held) pairs, one sample every ``step`` seconds."""
    samples = []
    for index, (state, held) in enumerate(states):
        samples.append({'time': index * step, 'identity': 'confirmed', 'state': state, 'held': held})
    return {'schema_version': 2, 'samples': samples, 'events': []}


S, T, L, N = ('sitting', None), ('standing', None), ('lying', None), ('not_measurable', None)
HS = ('not_measurable', 'sitting')


class EpisodeTests(unittest.TestCase):
    def test_short_gaps_are_bridged_and_long_ones_split(self):
        from aba_demo.session_measures import episodes, posture_series

        series = posture_series(posture_doc([S, S, T, T, N, N, T, T, N, N, N, N, N, T, T, S]))
        found = episodes(series, ('standing',), decoded=8.0)
        self.assertEqual([(e['start'], e['end']) for e in found], [(1.0, 4.0), (6.5, 7.5)])
        self.assertTrue(found[0]['start_seen'])     # sitting right before
        self.assertFalse(found[0]['end_seen'])      # an unmeasured stretch after
        self.assertFalse(found[1]['start_seen'])
        self.assertTrue(found[1]['end_seen'])

    def test_short_episodes_are_left_out_and_held_counts_as_posture(self):
        from aba_demo.session_measures import episodes, posture_series

        series = posture_series(posture_doc([S, T, S, HS, HS, S]))
        self.assertEqual(episodes(series, ('standing',), decoded=3.0), [])  # 0.5 s only
        self.assertEqual(series[3], (1.5, 'sitting', True))
        self.assertEqual(episodes(series, ('sitting',), decoded=3.0)[-1]['start'], 1.0)


class SessionMeasureTests(unittest.TestCase):
    def documents(self):
        posture = posture_doc([S] * 4 + [T] * 6 + [N] * 4 + [L] * 4 + [S] * 2)  # 10 s, 2 s unmeasured
        area = {'samples': [{'time': i * 0.5, 'identity': 'confirmed',
                             'area_state': 'away_from_area' if 4 <= i < 10 else 'at_area'} for i in range(20)]}
        return {'posture': posture, 'orientation': area}

    def test_summary_shares_and_episode_counts(self):
        from aba_demo.session_measures import session_measures

        measures = session_measures(self.documents(), 10.0, interval_seconds=5.0)
        summary = measures['summary']
        self.assertAlmostEqual(summary['posture']['measured_share'], 0.8)
        self.assertAlmostEqual(summary['posture']['sitting_share'], 3.0 / 8.0)
        self.assertAlmostEqual(summary['posture']['lying_share'], 2.0 / 8.0)
        self.assertEqual(summary['episodes']['standing'], {'count': 1, 'total': 3.0, 'longest': 3.0})
        self.assertEqual(summary['episodes']['lying']['count'], 1)
        self.assertEqual(summary['episodes']['away_from_area']['total'], 3.0)
        self.assertAlmostEqual(summary['area']['at_area_share'], 0.7)
        self.assertIsNone(summary['large_movements'])  # no movement channel
        self.assertEqual([e['kind'] for e in measures['episodes']], ['away_from_area', 'standing', 'lying'])  # same start: by kind

    def test_interval_sheet_rows(self):
        from aba_demo.session_measures import intervals_csv, session_measures

        measures = session_measures(self.documents(), 10.0, interval_seconds=5.0)
        first, second = measures['intervals']
        self.assertEqual((first['start'], first['end']), (0.0, 5.0))
        self.assertIsNone(first['posture'])        # the sample at 5 s is unmeasured
        self.assertEqual(first['area'], 'at_area')
        self.assertTrue(first['out_of_seat'])
        self.assertTrue(first['away_from_area'])
        self.assertEqual(second['posture'], None)  # 10 s is past the last sample
        self.assertEqual(second['area'], None)
        self.assertTrue(second['out_of_seat'])     # lying in 5-10 s
        self.assertFalse(second['away_from_area'])
        text = intervals_csv(measures).splitlines()
        self.assertEqual(text[0].split(',')[0], 'interval_start')
        self.assertEqual(text[1].split(',')[:2], ['0:00', '0:05'])
        self.assertIn('not_measured', text[2])

    def test_unmeasured_intervals_are_not_answered(self):
        from aba_demo.session_measures import session_measures

        measures = session_measures({'posture': posture_doc([N] * 20)}, 10.0)
        self.assertIsNone(measures['intervals'][0]['out_of_seat'])
        self.assertIsNone(measures['summary']['posture']['sitting_share'])


class ExportTests(unittest.TestCase):
    def test_csv_over_http(self):
        from fastapi.testclient import TestClient

        from aba_demo.live.api import create_app
        from aba_demo.live.library import SessionLibrary

        with tempfile.TemporaryDirectory() as directory:
            make_session(Path(directory) / 'one')
            library = SessionLibrary(directory)
            session_id = library.list()[0]['id']
            self.assertIsNotNone(library.review(session_id)['measures'])
            with TestClient(create_app(port=8767, library=library), base_url='http://127.0.0.1:8767') as client:
                sheet = client.get(f'/api/library/{session_id}/export/intervals.csv')
                self.assertEqual(sheet.status_code, 200)
                self.assertTrue(sheet.headers['content-type'].startswith('text/csv'))
                self.assertIn('attachment', sheet.headers['content-disposition'])
                self.assertTrue(sheet.content.startswith('﻿'.encode('utf-8')))
                episodes = client.get(f'/api/library/{session_id}/export/episodes.csv')
                self.assertEqual(episodes.text.lstrip('﻿').splitlines()[0],
                                 'kind,start,end,duration_seconds,start_seen,end_seen')
                self.assertEqual(client.get(f'/api/library/{session_id}/export/other.csv').status_code, 422)
                self.assertEqual(client.get('/api/library/missing/export/intervals.csv').status_code, 404)


if __name__ == '__main__':
    unittest.main()
