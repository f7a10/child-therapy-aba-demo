"""In-app analysis: upload -> select the child -> tracking with reselection -> channels -> review.

Uses fakes shaped like ReviewSession and the channel readers; no model, video or network.
"""
import base64
import hashlib
import json
import math
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from movement_fixtures import OTHER_BOX, TARGET_BOX, candidate
from test_session_timeline import two_events

CHILD_CLICK = (0.15, 0.5)      # inside the child's box only
AMBIGUOUS_CLICK = (0.35, 0.5)  # inside both boxes
JPEG = b'\xff\xd8fake-jpeg\xff\xd9'


class FakeAnalyzer:
    fps = 10.0
    frame_count = 61

    def __init__(self):
        self.frame_index = 0


class FakeReviewSession:
    """Minimal ReviewSession: confirmed until ``lost_at``, then latched until reselected."""
    lost_at = None

    def __init__(self, video, config, output_root):
        self.video = Path(video)
        self.config = config
        self.analyzer = FakeAnalyzer()
        self.audit = []
        self.selections = []
        self.pending = Path(output_root) / 'run' / 'observations.pending.json'
        self.closed = False
        self._lost = False
        self._update_preview()

    def _update_preview(self):
        self.preview = {'image': base64.b64encode(JPEG).decode('ascii'), 'width': 640, 'height': 360,
                        'time': self.analyzer.frame_index / self.analyzer.fps,
                        'boxes': [{'id': 7, 'xyxy': list(TARGET_BOX)},
                                  {'id': 3, 'xyxy': list(OTHER_BOX)}, {'id': None, 'xyxy': [0, 0, .1, .1]}]}

    def select(self, click, *, expected_target_id, confirmed=False):
        assert confirmed is True and expected_target_id == 7
        self.selections.append((self.analyzer.frame_index, list(click)))
        self._lost = False
        # Like ReviewSession: a click on a lost frame keeps that frame's loss row.
        if not self.audit or self.audit[-1]['identity'] == 'confirmed':
            self.audit.append({'identity': 'confirmed', 'reason': None})

    def skip_unselected(self, time_s):
        assert not self.selections
        self.analyzer.frame_index = int(math.floor(time_s * self.analyzer.fps + 1e-8))
        self.audit.append({'identity': 'uncertain', 'reason': 'select_target'})
        self._update_preview()
        return self.preview

    def advance(self, time_s):
        self.analyzer.frame_index = int(math.floor(time_s * self.analyzer.fps + 1e-8))
        if self.lost_at is not None and time_s >= self.lost_at and len(self.selections) == 1:
            self._lost = True
        self.audit.append({'identity': 'uncertain' if self._lost else 'confirmed',
                           'reason': 'target_lost_reselect' if self._lost else None})
        self._update_preview()
        return self.preview

    def finish(self, *, max_uncertain_fraction, progress=None):
        source = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.pending.parent.mkdir(parents=True)
        data = candidate(source)
        data['provenance']['quality']['uncertain_fraction'] = 0.05
        self.pending.write_text(json.dumps(data), encoding='utf-8')
        self.closed = True
        return {'quality': {'passed': True, 'uncertain_fraction': 0.05}}

    def close(self):
        self.closed = True


def posture_reader(video, pending, output_dir, *, detector, weights_name, progress, **_):
    source = hashlib.sha256(Path(video).read_bytes()).hexdigest()
    tracking = hashlib.sha256(Path(pending).read_bytes()).hexdigest()
    progress(1, 1)
    Path(output_dir).mkdir(parents=True)
    (Path(output_dir) / 'posture.pending.json').write_text(json.dumps(
        {**two_events(), 'source_sha256': source, 'tracking_candidate_sha256': tracking}),
        encoding='utf-8')


def failing_reader(*args, **kwargs):
    raise ValueError('not_measurable_here')


def unused_reader(*args, **kwargs):
    raise AssertionError('should not run')


def local_reader(per_channel):
    """Fake one-pass local reader built from per-channel fakes: (reports, errors)."""
    def read(video, pending, outputs, *, detector, task_region, weights_name, motion_estimator,
             progress):
        reports, errors = {}, {}
        for name, folder in outputs.items():
            options = {'task_region': task_region} if name == 'orientation' else {}
            try:
                reports[name] = per_channel[name](video, pending, folder, detector=detector,
                                                  weights_name=weights_name, progress=progress,
                                                  **options)
            except ValueError as error:
                errors[name] = error
        return reports, errors
    return read


def make_manager(root, *, session_class=FakeReviewSession, context=None, orientation=unused_reader):
    from aba_demo.live.analysis import AnalysisManager, ContextUnavailable, Pipeline
    from aba_demo.live.library import SessionLibrary

    def no_context():
        raise ContextUnavailable('provider_not_configured')

    pipeline = Pipeline(weights='yolo11s-pose.pt', review_session=session_class,
                        detector=lambda: object(), motion_estimator=lambda: object(),
                        readers={'local': local_reader({'posture': posture_reader,
                                                        'movement': failing_reader,
                                                        'orientation': orientation}),
                                 'context': unused_reader},
                        context_adapters=context or no_context)
    library = SessionLibrary(root)
    return library, AnalysisManager(library, pipeline,
                                    clock=lambda: datetime(2026, 10, 3, 12, 0, 0))


def upload(manager, name='Table work.mp4', payload=b'video-bytes' * 50):
    folder, video, title = manager.begin_upload(name)
    video.write_bytes(payload)
    return manager.create(folder, video, title)


def wait_for(job, *states, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = job.status()
        if status['state'] in states:
            return status
        time.sleep(0.01)
    raise AssertionError(f'job stayed in {job.status()["state"]}, wanted {states}')


class AnalysisJobTests(unittest.TestCase):
    def test_a_new_video_becomes_a_reviewable_session(self):
        with tempfile.TemporaryDirectory() as directory:
            library, manager = make_manager(Path(directory))
            job = upload(manager)
            status = wait_for(job, 'select')
            self.assertEqual([box['id'] for box in status['frame']['boxes']], [7, 3])
            self.assertEqual(job.jpeg(), JPEG)
            with self.assertRaisesRegex(ValueError, 'click_ambiguous'):
                job.select(*AMBIGUOUS_CLICK, activity='table')
            with self.assertRaisesRegex(ValueError, 'click_not_on_person'):
                job.select(0.95, 0.95, activity='table')
            with self.assertRaisesRegex(ValueError, 'invalid_activity'):
                job.select(*CHILD_CLICK, activity='dance')
            job.select(*CHILD_CLICK, activity='table', title='Table session')
            status = wait_for(job, 'done', 'failed')
            self.assertEqual((status['state'], status['error']), ('done', None))
            stages = {stage['name']: (stage['status'], stage['note']) for stage in status['stages']}
            self.assertEqual(stages, {
                'tracking': ('done', None), 'posture': ('done', None),
                'movement': ('failed', 'not_measurable_here'),
                'orientation': ('skipped', 'no_task_region'),
                'context': ('skipped', 'provider_not_configured')})
            self.assertEqual(status['session_id'], 'recorded-20261003-120000-table-work')
            review = library.review(status['session_id'])
            self.assertEqual((review['title'], review['activity'], review['channels']),
                             ('Table session', 'table', ['posture']))
            self.assertEqual(review['skipped'], {'movement': 'not_measurable_here',
                                                 'orientation': 'no_task_region',
                                                 'context': 'provider_not_configured'})
            self.assertEqual([(e['kind'], e['level']) for e in review['entries']],
                             [('stand_to_sit', 'info'), ('sit_to_stand', 'flag')])
            self.assertAlmostEqual(review['child_confirmed_fraction'], 0.95)
            self.assertAlmostEqual(status['child_confirmed_fraction'], 0.95)
            listed = library.list()
            self.assertEqual([(item['id'], item['moments'], item['flags']) for item in listed],
                             [(status['session_id'], len(review['groups']), 1)])

    def test_a_lost_child_pauses_tracking_for_the_therapist_to_reselect(self):
        class LosesChild(FakeReviewSession):
            lost_at = 2.0

        with tempfile.TemporaryDirectory() as directory:
            _, manager = make_manager(Path(directory), session_class=LosesChild)
            job = upload(manager)
            wait_for(job, 'select')
            job.select(*CHILD_CLICK, activity='movement')
            status = wait_for(job, 'reselect')
            self.assertEqual(status['frame']['time'], 2.0)
            version = status['frame']['version']
            job.skip()
            end = time.monotonic() + 10
            while (job.status()['frame'] or {}).get('version', version) == version:
                self.assertLess(time.monotonic(), end)
                time.sleep(0.01)
            status = job.status()
            self.assertEqual((status['state'], status['frame']['time']), ('reselect', 4.0))
            job.select(*CHILD_CLICK)
            status = wait_for(job, 'done', 'failed')  # not asked again for the same frame
            self.assertEqual((status['state'], status['reselections']), ('done', 1))

    def test_the_task_area_enables_the_orientation_channel(self):
        calls = []

        def orientation(video, pending, output_dir, *, task_region, **_):
            calls.append(task_region)
            raise ValueError('invalid_task_region')

        with tempfile.TemporaryDirectory() as directory:
            _, manager = make_manager(Path(directory), orientation=orientation)
            job = upload(manager)
            wait_for(job, 'select')
            with self.assertRaisesRegex(ValueError, 'invalid_task_region'):
                job.select(*CHILD_CLICK, activity='table', task_region=[0.5, 0.5, 0.4, 0.6])
            job.select(*CHILD_CLICK, activity='table', task_region=[0.5, 0.4, 0.7, 0.6])
            status = wait_for(job, 'done', 'failed')
            self.assertEqual(calls, [[0.5, 0.4, 0.7, 0.6]])
            self.assertEqual(status['stages'][3]['status'], 'failed')

    def test_cancel_removes_the_upload_and_only_one_analysis_runs_at_a_time(self):
        with tempfile.TemporaryDirectory() as directory:
            library, manager = make_manager(Path(directory))
            job = upload(manager)
            wait_for(job, 'select')
            with self.assertRaisesRegex(RuntimeError, 'analysis_in_progress'):
                manager.begin_upload('second.mp4')
            with self.assertRaisesRegex(ValueError, 'unsupported_video_type'):
                manager.begin_upload('notes.txt')
            manager.discard(job.id)
            wait_for(job, 'cancelled')
            job.join(5)
            self.assertFalse(job.folder.exists())
            self.assertEqual(library.list(), [])
            upload(manager, 'second.mp4')  # free again


    def test_an_unreadable_video_fails_with_a_clear_code(self):
        class Unreadable(FakeReviewSession):
            def __init__(self, *args):
                raise ValueError('OpenCV could not open the video')

        with tempfile.TemporaryDirectory() as directory:
            _, manager = make_manager(Path(directory), session_class=Unreadable)
            job = upload(manager)
            status = wait_for(job, 'failed')
            self.assertEqual(status['error'], 'video_unreadable')
            job.join(5)
            self.assertFalse(job.folder.exists())


class SelectLaterTests(unittest.TestCase):
    def test_the_child_can_be_selected_after_skipping_an_empty_opening(self):
        sessions = []

        class Recording(FakeReviewSession):
            def __init__(self, *args):
                super().__init__(*args)
                sessions.append(self)

        with tempfile.TemporaryDirectory() as directory:
            _, manager = make_manager(Path(directory), session_class=Recording)
            job = upload(manager)
            status = wait_for(job, 'select')
            version = status['frame']['version']
            job.skip()
            end = time.monotonic() + 10
            while job.status()['frame']['version'] == version:
                self.assertLess(time.monotonic(), end)
                time.sleep(0.01)
            self.assertEqual(job.status()['frame']['time'], 2.0)
            job.select(*CHILD_CLICK, activity='table')
            self.assertEqual(wait_for(job, 'done', 'failed')['state'], 'done')
            self.assertEqual(sessions[0].selections[0][0], 20)  # selected on the later frame
            self.assertEqual(sessions[0].audit[0]['reason'], 'select_target')


class AnalysisApiTests(unittest.TestCase):
    def test_upload_select_and_review_over_http(self):
        from fastapi.testclient import TestClient

        from aba_demo.live.api import create_app

        with tempfile.TemporaryDirectory() as directory:
            library, manager = make_manager(Path(directory))
            base = 'http://127.0.0.1:8767'
            headers = {'origin': base}
            app = create_app(port=8767, library=library, analyses=manager)
            with TestClient(app, base_url=base) as client:
                self.assertEqual(client.get('/api/library').json(), {'sessions': [], 'analysis': True})
                rejected = client.post('/api/analyses', content=b'x',
                                       headers={**headers, 'x-filename': 'clip.avi'})
                self.assertEqual(rejected.status_code, 400)
                created = client.post('/api/analyses', content=b'video-bytes' * 50,
                                      headers={**headers, 'x-filename': 'Table%20work.mp4'})
                self.assertEqual(created.status_code, 201)
                job_id = created.json()['id']
                job = manager.get(job_id)
                wait_for(job, 'select')
                self.assertEqual(client.get(f'/api/analyses/{job_id}/frame').content, JPEG)
                self.assertEqual(client.get('/api/analyses/current').json()['analysis']['id'], job_id)
                bad = client.post(f'/api/analyses/{job_id}/select', headers=headers,
                                  json={'x': AMBIGUOUS_CLICK[0], 'y': AMBIGUOUS_CLICK[1],
                                        'activity': 'table'})
                self.assertEqual((bad.status_code, bad.json()['error']), (400, 'click_ambiguous'))
                cross = client.post(f'/api/analyses/{job_id}/select',
                                    headers={'origin': 'http://evil.example'},
                                    json={'x': CHILD_CLICK[0], 'y': CHILD_CLICK[1], 'activity': 'table'})
                self.assertEqual(cross.status_code, 403)
                ok = client.post(f'/api/analyses/{job_id}/select', headers=headers,
                                 json={'x': CHILD_CLICK[0], 'y': CHILD_CLICK[1], 'activity': 'table'})
                self.assertEqual(ok.status_code, 200)
                session_id = wait_for(job, 'done')['session_id']
                sessions = client.get('/api/library').json()['sessions']
                self.assertEqual([item['id'] for item in sessions], [session_id])
                review = client.get(f'/api/library/{session_id}').json()
                self.assertEqual(review['summary']['posture']['bands'][0][2], 'standing')
                video = client.get(f'/api/library/{session_id}/video')
                self.assertEqual((video.status_code, video.content), (200, b'video-bytes' * 50))
                self.assertEqual(client.get('/api/library/missing').status_code, 404)
                self.assertEqual(client.get('/api/analyses/missing').status_code, 404)


class ReviewSummaryTests(unittest.TestCase):
    def test_bands_and_coverage_describe_a_session_without_events(self):
        from aba_demo.live.library import channel_summary

        samples = [{'time': 0.0, 'state': 'sitting'}, {'time': 0.2, 'state': 'sitting'},
                   {'time': 0.4, 'state': None}, {'time': 0.6, 'state': 'not_measurable'},
                   {'time': 0.8, 'state': 'sitting'}, {'time': 1.0, 'state': 'standing'}]
        summary = channel_summary('posture', {'samples': samples, 'events': []}, 1.2)
        self.assertAlmostEqual(summary['coverage'], 4 / 6)
        self.assertEqual(summary['bands'], [[0.0, 0.4, 'sitting'], [0.8, 1.0, 'sitting'],
                                            [1.0, 1.2, 'standing']])
        movement = channel_summary('movement', {'samples': [{'time': 0.0, 'state': 'measured'},
                                                            {'time': 0.2, 'state': None}]}, 0.4)
        self.assertEqual(movement, {'coverage': 0.5})
        context = channel_summary('context', {'moments': [{'status': 'read'}, {'status': 'unread'}]}, 1)
        self.assertEqual(context, {'moments': 2, 'read': 1})



class TailCheckTests(unittest.TestCase):
    def test_a_long_unreadable_tail_ends_tracking_at_the_last_real_frame(self):
        from unittest import mock

        from aba_demo.live import analysis

        class Analyzer:
            fps, frame_count, duration = 10.0, 100, 10.0

            def __init__(self, video, config):
                self.closed = False

            def close(self):
                self.closed = True

        for decodable, expected in ((95, 95), (98, 100), (100, 100)):
            with mock.patch('aba_demo.vision.VideoAnalyzer', Analyzer),                     mock.patch.object(analysis, 'decodable_frame_count', return_value=decodable):
                analyzer = analysis.tail_checked_analyzer('video.mp4', {})
            self.assertEqual((analyzer.frame_count, analyzer.duration),
                             (expected, expected / 10.0))


class SkipWithReviewedSessionTests(unittest.TestCase):
    def test_skipping_before_selection_keeps_a_dense_valid_audit(self):
        from aba_demo.colab_workflow import ReviewSession
        from aba_demo.live.analysis import skip_before_selection
        from aba_demo.movement_windows import load_tracking_candidate
        from aba_demo.vision import SIGNALS

        class Analyzer:
            """Synthetic decoder: the child (tracker id 2) is visible from frame 0."""
            def __init__(self, path, config):
                self.fps, self.frame_count, self.duration = 10, 51, 5.1
                self.frame_index, self.target_id = -1, None

            def preview(self):
                self.frame_index = max(0, self.frame_index)
                return {'image': '', 'time': self.frame_index / self.fps, 'boxes': []}

            def select_target(self, x, y):
                self.target_id = 2
                return {'identity': 'confirmed', 'target_id': 2}

            def analyze(self, time):
                self.frame_index = round(time * self.fps)
                confirmed = self.target_id == 2
                return {'time': time, 'identity': 'confirmed' if confirmed else 'uncertain',
                        'signals': dict.fromkeys(SIGNALS, False if confirmed else None),
                        'values': {'identity_reason': None if confirmed else 'select_target'},
                        'boxes': [{'id': 2, 'xyxy': [0.1, 0.2, 0.4, 0.9]}],
                        'target_box': [0.1, 0.2, 0.4, 0.9] if confirmed else None}

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'clip.mp4'
            video.write_bytes(b'synthetic')
            session = ReviewSession(video, {}, Path(directory) / 'runs', analyzer_factory=Analyzer)
            skip_before_selection(session, 1.0)
            skip_before_selection(session, 2.0)
            session.select([0.2, 0.5], expected_target_id=2, confirmed=True)
            session.finish(max_uncertain_fraction=0.5)
            data, _ = load_tracking_candidate(session.pending)
            audit = data['provenance']['causal_audit']
            self.assertEqual([row['frame_index'] for row in audit], list(range(51)))
            self.assertEqual({row['reason'] for row in audit[:20]}, {'select_target'})
            self.assertEqual(data['provenance']['initial_selection']['frame_index'], 20)

if __name__ == '__main__':
    unittest.main()
