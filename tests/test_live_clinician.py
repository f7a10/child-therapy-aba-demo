"""The therapist's review of each moment, and the library's still frames."""
import json
import tempfile
import unittest
from pathlib import Path

from test_live_library import make_session

BASE = 'http://127.0.0.1:8767'


class ClinicianReviewTests(unittest.TestCase):
    def library(self, directory):
        from aba_demo.live.library import SessionLibrary

        make_session(Path(directory) / 'one')
        library = SessionLibrary(directory)
        session_id = library.list()[0]['id']
        return library, session_id, [g['entry_ids'][0] for g in library.review(session_id)['groups']]

    def test_marks_are_kept_next_to_the_session_and_can_be_cleared(self):
        from aba_demo.live.library import REVIEW_NAME, SessionLibrary

        with tempfile.TemporaryDirectory() as directory:
            library, session_id, moments = self.library(directory)
            self.assertEqual(library.review(session_id)['clinician'], {})
            self.assertEqual(len(moments), 1)  # the fixture's two posture events form one moment
            library.mark(session_id, moments[0], 'not_seen')
            library.mark(session_id, moments[0], 'confirmed', '  stood at the table ')
            marks = SessionLibrary(directory).review(session_id)['clinician']  # survives a restart
            self.assertEqual({key: (m['verdict'], m['note']) for key, m in marks.items()},
                             {moments[0]: ('confirmed', 'stood at the table')})
            self.assertEqual(library.list()[0]['reviewed'], 1)
            library.mark(session_id, moments[0], None)
            self.assertEqual(library.review(session_id)['clinician'], {})
            self.assertEqual(library.list()[0]['reviewed'], 0)
            stored = json.loads((Path(directory) / 'one' / REVIEW_NAME).read_text(encoding='utf-8'))
            self.assertEqual(stored['kind'], 'clinician_review')
            self.assertFalse((Path(directory) / 'one' / 'clinician_review.partial').exists())

    def test_bad_marks_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            library, session_id, moments = self.library(directory)
            with self.assertRaises(KeyError):
                library.mark(session_id, 'tl-posture-unknown', 'confirmed')
            for verdict, note, code in (('maybe', '', 'invalid_verdict'), ('unsure', 'x' * 501, 'note_too_long'),
                                        (None, 'a note', 'note_needs_verdict')):
                with self.assertRaisesRegex(ValueError, code):
                    library.mark(session_id, moments[0], verdict, note)

    def test_marks_for_other_channel_bytes_are_dropped(self):
        from aba_demo.live.library import REVIEW_NAME

        with tempfile.TemporaryDirectory() as directory:
            library, session_id, moments = self.library(directory)
            library.mark(session_id, moments[0], 'confirmed')
            path = Path(directory) / 'one' / REVIEW_NAME
            document = json.loads(path.read_text(encoding='utf-8'))
            document['binding']['channels']['posture'] = '0' * 64
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertEqual(library.review(session_id)['clinician'], {})
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(library.review(session_id)['clinician'], {})

    def test_marks_over_http(self):
        from fastapi.testclient import TestClient

        from aba_demo.live.api import create_app

        with tempfile.TemporaryDirectory() as directory:
            library, session_id, moments = self.library(directory)
            with TestClient(create_app(port=8767, library=library), base_url=BASE) as client:
                url = f'/api/library/{session_id}/moments/{moments[0]}'
                done = client.put(url, json={'verdict': 'unsure', 'note': 'hidden by the table'},
                                  headers={'origin': BASE})
                self.assertEqual(done.status_code, 200)
                self.assertEqual(done.json()['clinician'][moments[0]]['verdict'], 'unsure')
                self.assertEqual(client.get(f'/api/library/{session_id}').json()['clinician'][moments[0]]['note'],
                                 'hidden by the table')
                self.assertEqual(client.put(url, json={'verdict': 'yes'}, headers={'origin': BASE}).status_code, 422)
                self.assertEqual(client.put(f'/api/library/{session_id}/moments/nope', json={'verdict': None},
                                            headers={'origin': BASE}).status_code, 404)
                self.assertEqual(client.put(url, json={'verdict': None},
                                            headers={'origin': 'http://evil.example'}).status_code, 403)
                # The fixture's video is not a real video, so it has no still.
                self.assertEqual(client.get(f'/api/library/{session_id}/thumbnail').status_code, 404)


class ThumbnailTests(unittest.TestCase):
    def test_a_small_still_is_taken_from_the_video(self):
        import cv2
        import numpy as np

        from aba_demo.live.library import thumbnail_jpeg

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'clip.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (640, 360))
            for index in range(20):
                writer.write(np.full((360, 640, 3), index * 10, np.uint8))
            writer.release()
            image = cv2.imdecode(np.frombuffer(thumbnail_jpeg(video, 1.0), np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(image.shape[:2], (180, 320))
            self.assertIsNone(thumbnail_jpeg(Path(directory) / 'missing.mp4', 0.0))


if __name__ == '__main__':
    unittest.main()
