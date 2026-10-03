"""Recorded-session library: each folder with a session.json manifest becomes a session."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from movement_fixtures import candidate
from test_session_timeline import two_events


def make_session(folder: Path, title='Table session', *, channel_source=None):
    folder.mkdir(parents=True)
    video = folder / 'video.mp4'
    video.write_bytes(folder.name.encode('utf-8') * 64)
    source = hashlib.sha256(video.read_bytes()).hexdigest()
    observations = folder / 'observations.pending.json'
    observations.write_text(json.dumps(candidate(source)), encoding='utf-8')
    tracking = hashlib.sha256(observations.read_bytes()).hexdigest()
    posture = folder / 'posture.pending.json'
    posture.write_text(json.dumps({**two_events(), 'source_sha256': channel_source or source,
                                   'tracking_candidate_sha256': tracking}), encoding='utf-8')
    manifest = {'title': title, 'video': 'video.mp4', 'observations': 'observations.pending.json',
                'channels': ['posture.pending.json']}
    (folder / 'session.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    return manifest


class SessionLibraryTests(unittest.TestCase):
    def test_every_manifest_folder_becomes_a_recorded_session(self):
        from aba_demo.live.scenarios import load_session_library

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_session(root / 'Mastered Area', title='جلسة الطاولة')
            make_session(root / 'reference')
            (root / 'notes').mkdir()  # no manifest: ignored
            sessions = load_session_library(root)
            self.assertEqual([s.id for s in sessions], ['recorded-mastered-area', 'recorded-reference'])
            described = sessions[0].describe()
            self.assertEqual((described['title'], described['kind'], described['video']),
                             ('جلسة الطاولة', 'precomputed', True))
            self.assertEqual(described['channels'], ['posture'])
            self.assertEqual(sessions[0].build_moments().due(10.0)[0]['channel'], 'posture')

    def test_a_broken_session_is_reported_by_folder(self):
        from aba_demo.live.scenarios import load_session_library

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_session(root / 'bad', channel_source='e' * 64)
            with self.assertRaisesRegex(ValueError, 'bad'):
                load_session_library(root)
            other = Path(directory) / 'extra'
            make_session(other / 'odd')
            manifest = json.loads((other / 'odd' / 'session.json').read_text(encoding='utf-8'))
            (other / 'odd' / 'session.json').write_text(json.dumps({**manifest, 'note': 'x'}),
                                                        encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'odd'):
                load_session_library(other)
            with self.assertRaisesRegex(ValueError, 'session_library_not_found'):
                load_session_library(Path(directory) / 'missing')


class ProductScenarioListTests(unittest.TestCase):
    def test_synthetic_engineering_scenarios_can_be_left_out(self):
        from aba_demo.live.runtime import SessionManager
        from aba_demo.live.scenarios import SCENARIOS, load_session_library

        with tempfile.TemporaryDirectory() as directory:
            make_session(Path(directory) / 'one')
            recorded = load_session_library(Path(directory))
            product = SessionManager(extra_scenarios=recorded, include_synthetic=False)
            self.assertEqual([s['id'] for s in product.scenarios()], ['recorded-one'])
            with self.assertRaisesRegex(ValueError, 'Unknown scenario'):
                product.create('table-routine')
            engineering = SessionManager(extra_scenarios=recorded)
            self.assertEqual(len(engineering.scenarios()), len(SCENARIOS) + 1)


if __name__ == '__main__':
    unittest.main()
