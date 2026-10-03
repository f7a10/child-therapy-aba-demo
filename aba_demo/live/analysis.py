"""In-app analysis of a new video: from upload to a reviewable session.

One job per uploaded video, run in its own worker thread (one at a time: the
pose model uses the local GPU):

1. The first frame is shown with every tracked person; the therapist clicks the
   child, sets the activity, and may draw the task area (needed for channel 4).
2. Tracking runs forward with the reviewed ``ReviewSession``. When the child is
   lost and identity latches, the job pauses on the current frame for the
   therapist to click the child again (never automatic), skip ahead while the
   child is out of view, or continue without further prompts.
3. The local channels run on the tracking file (posture, large movement, and
   orientation when a task area was drawn), then the context channel sends its
   sparse moments to the configured provider (always on in the site: approved
   by the project owner; privacy flags unchanged). A context failure leaves the
   local channels intact.
4. The session folder gets its ``session.json`` and joins the library.

The therapist's commands reach the worker through a queue; the worker is the only
thread touching the analyzer. Errors are reported as short codes, never as model
output or credentials.
"""
import base64
import json
import math
import queue
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from ..activities import ACTIVITIES
from ..export import MAX_TRAILING_DECODE_GAP_FRAMES
from .scenarios import MANIFEST_NAME

STAGES = ('tracking', 'posture', 'movement', 'orientation', 'context')
VIDEO_SUFFIXES = frozenset({'.mp4', '.m4v', '.mov', '.webm'})
MAX_UPLOAD_BYTES = 8 * 1024 ** 3
# Tracking advances in steps so a lost child is noticed within about a second.
STEP_SECONDS = 1.0
SKIP_SECONDS = 2.0
# Share of the session the child may be unconfirmed (out of view or awaiting
# reselection). Unconfirmed time is never measured by any channel.
MAX_UNCERTAIN_FRACTION = 0.25
MAX_RESELECTIONS = 12
TERMINAL = frozenset({'done', 'failed', 'cancelled'})
ACTIVE_WAITS = frozenset({'select', 'reselect'})


class AnalysisCancelled(Exception):
    pass


class ContextUnavailable(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def tracking_config(weights, device):
    """The reviewed tracking profile used for the recorded sessions."""
    return {'weights': str(weights), 'device': device, 'sample_hz': 5, 'task_targets': [],
            'seat_roi': None, 'identity_recovery_max_gap_s': 0.5,
            'tracker_profile': 'botsort_reid', 'candidate_overlap_policy': 'human_review_required'}


def clicked_box(boxes, x, y):
    """The one tracked person under a click, as ``TargetLock.select`` decides it."""
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
        raise ValueError('click_outside_frame')
    hits = [box for box in boxes if box.get('id') is not None
            and box['xyxy'][0] <= x <= box['xyxy'][2] and box['xyxy'][1] <= y <= box['xyxy'][3]]
    if not hits:
        raise ValueError('click_not_on_person')
    if len(hits) > 1:
        raise ValueError('click_ambiguous')
    return hits[0]


def valid_region(region):
    return (isinstance(region, (list, tuple)) and len(region) == 4
            and all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in region)
            and region[0] < region[2] and region[1] < region[3])


class Pipeline:
    """The heavy parts, injectable for tests. Defaults use the local models."""

    def __init__(self, *, weights, device=None, key_file=None, context_model=None,
                 context_provider=None, review_session=None, detector=None,
                 motion_estimator=None, readers=None, context_adapters=None):
        self.weights = Path(weights)
        self.device = device
        self.key_file = key_file
        self.context_model = context_model
        self.context_provider = context_provider
        self._review_session = review_session
        self._detector_factory = detector
        self._motion_estimator = motion_estimator
        self._readers = readers
        self._context_adapters = context_adapters
        self._detector = None

    def review_session(self, video, output_root):
        if self._review_session is not None:
            return self._review_session(video, tracking_config(self.weights, self.device), output_root)
        from ..colab_workflow import ReviewSession

        return ReviewSession(video, tracking_config(self.weights, self.device), output_root)

    def detector(self):
        if self._detector is None:
            if self._detector_factory is not None:
                self._detector = self._detector_factory()
            else:
                from ..posture_reader import YoloPoseDetector

                self._detector = YoloPoseDetector(self.weights, device=self.device)
        return self._detector

    def motion_estimator(self):
        if self._motion_estimator is not None:
            return self._motion_estimator()
        from ..large_movement_reader import BackgroundMotionEstimator

        return BackgroundMotionEstimator()

    def readers(self):
        if self._readers is not None:
            return self._readers
        from ..context_channel_reader import read_context
        from ..large_movement_reader import read_large_movement
        from ..orientation_reader import read_orientation
        from ..posture_reader import read_posture

        return {'posture': read_posture, 'movement': read_large_movement,
                'orientation': read_orientation, 'context': read_context}

    def context_adapters(self):
        """One adapter per activity, or ContextUnavailable with a short code."""
        if self._context_adapters is not None:
            return self._context_adapters()
        if not (self.context_model and self.context_provider and self.key_file):
            raise ContextUnavailable('provider_not_configured')
        from ..context_channel_schema import CONTEXT_TASKS
        from ..openrouter_context import OpenRouterContextAdapter
        try:
            key = _read_local_key(Path(self.key_file))
        except ValueError:
            raise ContextUnavailable('invalid_config') from None
        if key is None:
            raise ContextUnavailable('provider_not_configured')
        try:
            return {activity: OpenRouterContextAdapter(
                api_key=key, model=self.context_model, max_tokens=8192,
                task=CONTEXT_TASKS[activity], provider_order=[self.context_provider],
                reasoning={'effort': 'low', 'exclude': True}) for activity in ACTIVITIES}
        finally:
            key = None


class AnalysisJob:
    def __init__(self, job_id, folder, video, title, pipeline, on_done, *, clock=datetime.now):
        self.id = job_id
        self.folder = Path(folder)
        self.video = Path(video)
        self.title = title
        self.pipeline = pipeline
        self._on_done = on_done
        self._clock = clock
        self._lock = threading.Lock()
        self._commands = queue.Queue()
        self._cancelled = threading.Event()
        self.state = 'preparing'
        self.stage = None
        self.progress = None
        self.error = None
        self.frame = None
        self.frame_jpeg = None
        self.frame_version = 0
        self.reselections = 0
        self.prompts = True
        self.settings = None
        self.stages = {name: {'status': 'pending', 'note': None} for name in STAGES}
        self.session_id = None
        self.child_confirmed_fraction = None
        self._thread = threading.Thread(target=self._run, name=f'analysis-{job_id}', daemon=True)

    def start(self):
        self._thread.start()

    def join(self, timeout=None):
        self._thread.join(timeout)

    # ----- called from the API (any thread) -----

    def status(self):
        with self._lock:
            frame = None if self.frame is None else dict(self.frame, version=self.frame_version)
            return {'id': self.id, 'title': self.title, 'state': self.state, 'stage': self.stage,
                    'progress': self.progress, 'error': self.error, 'frame': frame,
                    'reselections': self.reselections, 'max_reselections': MAX_RESELECTIONS,
                    'stages': [dict(self.stages[name], name=name) for name in STAGES],
                    'session_id': self.session_id,
                    'child_confirmed_fraction': self.child_confirmed_fraction}

    def jpeg(self):
        with self._lock:
            return self.frame_jpeg

    def select(self, x, y, *, activity=None, task_region=None, title=None):
        """Validate a click on the shown frame now; the worker applies it."""
        with self._lock:
            state, frame = self.state, self.frame
        if state not in ACTIVE_WAITS or frame is None:
            raise ValueError('not_waiting_for_selection')
        box = clicked_box(frame['boxes'], x, y)
        command = {'type': 'select', 'click': [float(x), float(y)], 'target_id': box['id']}
        if state == 'select':
            if activity not in ACTIVITIES:
                raise ValueError('invalid_activity')
            if task_region is not None and not valid_region(task_region):
                raise ValueError('invalid_task_region')
            title = (title or self.title).strip()
            if not 1 <= len(title) <= 120:
                raise ValueError('invalid_title')
            command.update(activity=activity, task_region=None if task_region is None
                           else [float(v) for v in task_region], title=title)
        elif self.reselections >= MAX_RESELECTIONS:
            raise ValueError('reselection_limit')
        self._commands.put(command)

    def skip(self):
        if self.state != 'reselect':
            raise ValueError('not_waiting_for_selection')
        self._commands.put({'type': 'skip'})

    def continue_without(self):
        if self.state != 'reselect':
            raise ValueError('not_waiting_for_selection')
        self._commands.put({'type': 'continue'})

    def cancel(self):
        self._cancelled.set()
        self._commands.put({'type': 'cancel'})

    # ----- worker -----

    def _set(self, **values):
        with self._lock:
            for key, value in values.items():
                setattr(self, key, value)

    def _stage(self, name, status, note=None):
        with self._lock:
            self.stages[name] = {'status': status, 'note': note}
            if status == 'running':
                self.stage, self.progress = name, None

    def _progress(self, done, total):
        if self._cancelled.is_set():
            raise AnalysisCancelled()
        self._set(progress={'done': int(done), 'total': int(total)})

    def _show(self, preview):
        image = base64.b64decode(preview['image'])
        frame = {'time': preview['time'], 'width': preview['width'], 'height': preview['height'],
                 'boxes': [{'id': box['id'], 'xyxy': list(box['xyxy'])}
                           for box in preview['boxes'] if box.get('id') is not None]}
        with self._lock:
            self.frame, self.frame_jpeg = frame, image
            self.frame_version += 1

    def _wait(self, state):
        self._set(state=state)
        while True:
            command = self._commands.get()
            if command['type'] == 'cancel' or self._cancelled.is_set():
                raise AnalysisCancelled()
            if state == 'select' and command['type'] != 'select':
                continue
            return command

    def _run(self):
        session = None
        try:
            try:
                session = self.pipeline.review_session(self.video, self.folder / 'runs')
            except (ValueError, EOFError) as error:
                # OpenCV cannot decode it, or its metadata (FPS / frame count) is unusable.
                raise ValueError('video_unreadable') from error
            self._show(session.preview)
            command = self._wait('select')
            self.settings = {key: command[key] for key in ('activity', 'task_region')}
            self._set(title=command['title'])
            self._stage('tracking', 'running')
            self._set(state='running', frame=None)
            session.select(command['click'], expected_target_id=command['target_id'], confirmed=True)
            report = self._track(session)
            session = None
            uncertain = report['quality']['uncertain_fraction']
            self._set(child_confirmed_fraction=1.0 - uncertain)
            if not report['quality']['passed']:
                raise ValueError('child_not_confirmed_enough')
            self._stage('tracking', 'done')
            channels, skipped = self._channels(Path(report['pending']))
            if not channels:
                raise ValueError('no_channel_produced')
            self._write_manifest(Path(report['pending']), channels, skipped)
            self._set(session_id=self._on_done(self.folder), state='done', stage=None, progress=None)
        except AnalysisCancelled:
            self._finish_failed('cancelled', None)
        except Exception as error:  # reported as a short code only
            self._finish_failed('failed', _code(error))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _finish_failed(self, state, code):
        with self._lock:
            if self.stage and self.stages[self.stage]['status'] == 'running':
                self.stages[self.stage] = {'status': 'failed', 'note': code}
            self.state, self.error, self.frame, self.frame_jpeg = state, code, None, None
        # The upload and partial outputs are removed; nothing half-made joins the library.
        shutil.rmtree(self.folder, ignore_errors=True)

    def _latched(self, session):
        row = session.audit[-1] if session.audit else None
        return bool(row and row['identity'] != 'confirmed'
                    and str(row.get('reason') or '').endswith('_reselect'))

    def _track(self, session):
        analyzer = session.analyzer
        fps, frames = analyzer.fps, analyzer.frame_count
        # Forward steps stop short of the end; finish() decodes the tail with its EOF tolerance.
        last_step = (frames - 2 - MAX_TRAILING_DECODE_GAP_FRAMES) / fps
        time = analyzer.frame_index / fps
        while time + STEP_SECONDS < last_step:
            if self._cancelled.is_set():
                raise AnalysisCancelled()
            time += STEP_SECONDS
            session.advance(time)
            self._progress(analyzer.frame_index + 1, frames)
            while self.prompts and self._latched(session) and self.reselections < MAX_RESELECTIONS:
                self._show(session.preview)
                command = self._wait('reselect')
                if command['type'] == 'select':
                    session.select(command['click'], expected_target_id=command['target_id'],
                                   confirmed=True)
                    # The audit keeps the loss row at the click's own frame (recovery starts
                    # at the next decoded frame), so look again only after the next step.
                    self._set(reselections=self.reselections + 1, state='running', frame=None)
                    break
                elif command['type'] == 'skip':
                    target = min(time + SKIP_SECONDS, last_step)
                    if target > time:
                        time = target
                        session.advance(time)
                        self._progress(analyzer.frame_index + 1, frames)
                    else:
                        self._set(prompts=False)
                else:
                    self._set(prompts=False)
                self._set(state='running', frame=None)
        report = session.finish(max_uncertain_fraction=MAX_UNCERTAIN_FRACTION,
                                progress=self._progress)
        return dict(report, pending=str(session.pending))

    def _channels(self, pending):
        readers = self.pipeline.readers()
        channels, skipped = {}, {}
        local = [
            ('posture', 'posture.pending.json', {}),
            ('movement', 'large_movement.pending.json',
             {'motion_estimator': self.pipeline.motion_estimator()}),
        ]
        if self.settings['task_region'] is not None:
            local.append(('orientation', 'orientation.pending.json',
                          {'task_region': self.settings['task_region']}))
        else:
            self._stage('orientation', 'skipped', 'no_task_region')
            skipped['orientation'] = 'no_task_region'
        for name, filename, options in local:
            self._stage(name, 'running')
            try:
                readers[name](self.video, pending, self.folder / name,
                              detector=self.pipeline.detector(),
                              weights_name=self.pipeline.weights.name,
                              progress=self._progress, **options)
            except AnalysisCancelled:
                raise
            except Exception as error:
                self._stage(name, 'failed', _code(error))
                skipped[name] = _code(error)
                continue
            channels[name] = self.folder / name / filename
            self._stage(name, 'done')
        self._context(readers['context'], pending, channels, skipped)
        return channels, skipped

    def _context(self, read_context, pending, channels, skipped):
        self._stage('context', 'running')
        if not channels:
            self._stage('context', 'skipped', 'no_local_channel')
            skipped['context'] = 'no_local_channel'
            return
        data = json.loads(pending.read_bytes().decode('utf-8'))
        from ..movement_windows import decoded_seconds

        segments = [{'start_time': 0.0, 'end_time': decoded_seconds(data),
                     'activity': self.settings['activity']}]
        try:
            adapters = self.pipeline.context_adapters()
            options = dict(activity_segments=segments, model=self.pipeline.context_model or '-',
                           provider=self.pipeline.context_provider or '-')
            plan = read_context(self.video, pending, list(channels.values()), self.folder / 'context',
                                adapters, max_requests=None, plan_only=True, **options)
            if plan['moments'] == 0:
                self._stage('context', 'skipped', 'no_moments')
                skipped['context'] = 'no_moments'
                return
            read_context(self.video, pending, list(channels.values()), self.folder / 'context',
                         adapters, max_requests=2 * plan['moments'],
                         min_request_interval=2.0, rate_limit_wait=30.0,
                         progress=self._progress, **options)
        except AnalysisCancelled:
            raise
        except ContextUnavailable as error:
            self._stage('context', 'skipped', error.code)
            skipped['context'] = error.code
            return
        except Exception as error:
            self._stage('context', 'failed', _code(error))
            skipped['context'] = _code(error)
            return
        channels['context'] = self.folder / 'context' / 'context_channel.pending.json'
        self._stage('context', 'done')

    def _write_manifest(self, pending, channels, skipped):
        manifest = {
            'title': self.title, 'video': self.video.name,
            'observations': pending.relative_to(self.folder).as_posix(),
            'channels': [path.relative_to(self.folder).as_posix() for path in channels.values()],
            'activity': self.settings['activity'],
            'created': self._clock().isoformat(timespec='seconds'),
            'skipped': skipped,
        }
        (self.folder / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')


def _read_local_key(path):
    """The reviewed local credential reader (scripts/probe_openrouter_context.py)."""
    import importlib.util

    script = Path(__file__).resolve().parents[2] / 'scripts' / 'probe_openrouter_context.py'
    spec = importlib.util.spec_from_file_location('probe_openrouter_context', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_local_key(path)


def _code(error):
    """A short, content-free error code."""
    code = getattr(error, 'code', None)
    if isinstance(code, str):
        return code
    text = str(error) if isinstance(error, ValueError) else type(error).__name__
    text = text.strip().splitlines()[0] if text.strip() else type(error).__name__
    return text[:80]


class AnalysisManager:
    """Single-operator jobs; one runs at a time because they share the GPU."""

    def __init__(self, library, pipeline, *, clock=datetime.now):
        self.library = library
        self.pipeline = pipeline
        self._clock = clock
        self._jobs = {}
        self._lock = threading.Lock()

    def _active(self):
        return [job for job in self._jobs.values() if job.state not in TERMINAL]

    def current(self):
        with self._lock:
            active = self._active()
        return active[0].status() if active else None

    def begin_upload(self, filename):
        """A new session folder and the path the upload is written to."""
        name = Path(str(filename or '')).name
        suffix = Path(name).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise ValueError('unsupported_video_type')
        with self._lock:
            if self._active():
                raise RuntimeError('analysis_in_progress')
        title = Path(name).stem.strip()[:120] or 'Session'
        folder = self.library.new_folder(title, self._clock().strftime('%Y%m%d-%H%M%S'))
        return folder, folder / f'video{suffix}', title

    def create(self, folder, video, title):
        def done(path):
            self.library.reload()
            return self.library.id_for_folder(path)

        with self._lock:
            if self._active():
                shutil.rmtree(folder, ignore_errors=True)
                raise RuntimeError('analysis_in_progress')
            job = AnalysisJob(uuid.uuid4().hex[:12], folder, video, title, self.pipeline, done,
                              clock=self._clock)
            self._jobs[job.id] = job
        job.start()
        return job

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def discard(self, job_id):
        job = self.get(job_id)
        if job.state not in TERMINAL:
            job.cancel()
        with self._lock:
            if job.state in TERMINAL:
                self._jobs.pop(job_id, None)

    def shutdown(self):
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.state not in TERMINAL:
                job.cancel()
        for job in jobs:
            job.join(timeout=5)


__all__ = ['AnalysisJob', 'AnalysisManager', 'ContextUnavailable', 'Pipeline', 'STAGES',
           'clicked_box']
