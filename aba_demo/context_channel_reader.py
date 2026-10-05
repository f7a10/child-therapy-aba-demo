"""Context channel reader: a few frames per locally measured event, sent for closed notes.

Moments come only from events the local channels already produced (posture, large
movement, orientation), each read from 2-4 confirmed-identity samples of the same
tracked child inside the event. Frames are re-decoded from the SHA-verified source;
other tracked people are outlined in red and the child in green. Raw model output is
never stored; only the validated closed-enum observation is kept. Writes a pending,
source- and tracking-bound ``context_channel.pending.json`` outside the repository.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import threading
import time as clock

from .activities import _validate_segments, activity_at
from .channel_events import reading_for_document
from .colab_workflow import _write_bytes
from .context_channel_schema import (
    ANCHOR_CHANNELS, CONTEXT_TASKS, MAX_FRAMES, MAX_MOMENTS, MIN_FRAMES, PROMPT_SHA256,
    context_events, encode_context_channel_document)
from .export import file_sha256
from .grouping import group_by_time
from .movement_frames import SequentialFrameReader, build_movement_window
from .movement_windows import _target_samples, decoded_seconds, load_tracking_candidate
from .openrouter_context import OpenRouterContextError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAX_RATE_LIMIT_WAITS = 2
# Pause before the one retry after a provider outage (capped by the rate-limit wait).
RETRY_PAUSE_SECONDS = 5.0
MAX_PARALLEL = 4


class _Stopped(Exception):
    """A parallel request not started because another one hit a terminal error."""
TERMINAL_PROVIDER_CODES = frozenset({
    'invalid_input', 'invalid_config', 'provider_not_configured', 'provider_unauthorized',
    'provider_credit_exhausted', 'provider_no_compatible_route', 'provider_request_rejected',
    'provider_request_too_large',
})


def _spread(items, count):
    """Up to ``count`` items evenly spread, always keeping the first and last."""
    if len(items) <= count:
        return list(items)
    return [items[round(part * (len(items) - 1) / (count - 1))] for part in range(count)]


def plan_context_moments(data, events, *, max_frames=3, max_moments=MAX_MOMENTS):
    """Return (moments, skipped) for unified anchor ``events`` of one tracking candidate.

    Anchor events that happen together form one moment (one question). A moment
    uses the confirmed samples inside it that keep its first tracked target; a
    moment with fewer than two such samples is skipped.
    """
    if type(max_frames) is not int or not MIN_FRAMES <= max_frames <= MAX_FRAMES:
        raise ValueError('invalid_context_parameters')
    time_of_frame = {row['frame_index']: row['time'] for row in data['provenance']['causal_audit']}
    targets = sorted(_target_samples(data).items())
    anchors = [dict(event, sort_key=event['channel'] + ':' + event['event_id'])
               for event in events if event['channel'] in ANCHOR_CHANNELS]
    moments, skipped = [], 0
    for group in group_by_time(anchors, key='sort_key'):
        start = min(event['start_time'] for event in group)
        end = max(event['end_time'] for event in group)
        inside = [(index, sample) for index, sample in targets
                  if start <= time_of_frame[index] <= end]
        if inside:
            first_target = inside[0][1][0]
            inside = [(index, sample) for index, sample in inside if sample[0] == first_target]
        if len(inside) < MIN_FRAMES or len(moments) >= max_moments:
            skipped += 1
            continue
        moments.append({
            'moment_id': f'ctx-{len(moments):06d}',
            'anchors': sorted(({'channel': e['channel'], 'event_id': e['event_id']}
                               for e in group), key=lambda a: a['event_id']),
            'start_time': start, 'end_time': end,
            'detected_time': max(event['detected_time'] for event in group),
            'frames': [{'time': time_of_frame[index], 'frame_index': index,
                        'target_box': sample[1], 'other_boxes': sample[3]}
                       for index, sample in _spread(inside, max_frames)]})
    return moments, skipped


def send_windows(moments, windows, adapter_of, source_sha256, *, max_requests,
                 min_request_interval=0.0, rate_limit_wait=0.0, sleep=clock.sleep,
                 progress=None, max_parallel=1):
    """Ask one question per window; return ``(answers, stats)``.

    ``answers[i]`` is ``(observation, None)`` or ``(None, failure_code)`` for
    ``windows[i]``. Request starts are spaced by ``min_request_interval``; a rate
    limit waits and retries, an invalid response is retried once, both only while
    every moment not yet started keeps one request of the hard ``max_requests``
    cap. A terminal provider error stops requests not yet started and is raised
    with ``requests_used``. With ``max_parallel`` > 1 several requests wait on the
    provider at once; the answers and their order do not change.
    """
    state = {'requests_used': 0, 'rate_limit_waits': 0, 'started': 0, 'done': 0,
             'last_request': None, 'stop': None}
    providers, models, failure_codes = set(), set(), Counter()
    lock, start_lock = threading.Lock(), threading.Lock()

    def begin_attempt(first):
        with start_lock:
            if state['stop'] is not None:
                raise _Stopped()
            last = state['last_request']
            if last is not None and min_request_interval:
                sleep(max(0.0, min_request_interval - (clock.monotonic() - last)))
            with lock:
                state['requests_used'] += 1
                state['started'] += first
                state['last_request'] = clock.monotonic()

    def can_retry():
        # Every moment whose first request has not started yet keeps one request reserved.
        with lock:
            return state['requests_used'] + len(moments) - state['started'] < max_requests

    def ask(position):
        moment, window = moments[position], windows[position]
        observation, failure, retried, first = None, None, False, True
        while True:
            begin_attempt(first)
            first = False
            try:
                result = adapter_of(moment).analyze(window['frames'],
                                                    source_sha256=source_sha256)
            except OpenRouterContextError as error:
                retry = can_retry()
                with lock:
                    wait = (error.code == 'provider_rate_limited' and rate_limit_wait
                            and state['rate_limit_waits'] < MAX_RATE_LIMIT_WAITS and retry)
                    if wait:
                        state['rate_limit_waits'] += 1
                if wait:
                    sleep(rate_limit_wait)
                    continue
                if error.code in TERMINAL_PROVIDER_CODES:
                    raise
                failure = error.code + (':' + error.detail if error.detail else '')
                with lock:
                    failure_codes[failure] += 1
                # An invalid answer or a brief provider outage is tried once more.
                if (error.code in ('provider_response_invalid', 'provider_unavailable')
                        and not retried and retry):
                    retried = True
                    if error.code == 'provider_unavailable' and rate_limit_wait:
                        sleep(min(rate_limit_wait, RETRY_PAUSE_SECONDS))
                    continue
                break
            if not isinstance(result, dict) or not isinstance(result.get('observation'), dict):
                raise ValueError('invalid_adapter_result')
            observation = dict(result['observation'])
            provenance = result.get('provenance') or {}
            with lock:
                providers.add(str(provenance.get('endpoint_provider')))
                models.add(str(provenance.get('resolved_model')))
            break
        with lock:
            state['done'] += 1
            done = state['done']
        if progress:
            progress(done, len(moments))
        return observation, None if observation else failure

    def ask_or_stop_others(position):
        try:
            return ask(position)
        except _Stopped:
            raise
        except BaseException as error:
            state['stop'] = error  # requests not yet started are not sent
            raise

    answers = [None] * len(moments)
    try:
        if max_parallel == 1:
            for position in range(len(moments)):
                answers[position] = ask(position)
        else:
            # Moments are independent: several requests wait on the provider at once,
            # while the request spacing, the retry rules and the hard cap stay shared.
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = [pool.submit(ask_or_stop_others, position)
                           for position in range(len(moments))]
                error = None
                for position, future in enumerate(futures):
                    try:
                        answers[position] = future.result()
                    except _Stopped:
                        continue
                    except BaseException as failure:
                        error = error or failure
                if error is not None:
                    raise error
    except OpenRouterContextError as error:
        if error.code in TERMINAL_PROVIDER_CODES:
            error.requests_used = state['requests_used']
        raise
    return answers, {'requests_used': state['requests_used'],
                     'rate_limit_waits': state['rate_limit_waits'],
                     'failure_codes': failure_codes, 'providers': providers, 'models': models}


def read_context(video_path, candidate_path, channel_paths, output_dir, adapters, *,
                 activity_segments, model, provider, max_requests, max_frames=3, max_moments=MAX_MOMENTS,
                 min_request_interval=0.0, rate_limit_wait=0.0,
                 frame_reader_factory=SequentialFrameReader, sleep=clock.sleep,
                 progress=None, plan_only=False, max_parallel=1,
                 repository_root=REPOSITORY_ROOT):
    """Read context notes for the local channels' events; return counts only.

    ``adapters`` maps each therapist-set activity to an adapter asking that
    activity's question set; ``activity_segments`` must tile the decoded session.
    """
    video_path, output_dir = Path(video_path), Path(output_dir).resolve()
    if output_dir.is_relative_to(Path(repository_root).resolve()):
        raise ValueError('output_inside_repository')
    pending = output_dir / 'context_channel.pending.json'
    report_path = output_dir / 'context-report.json'
    if pending.exists() or report_path.exists():
        raise ValueError('context_candidate_exists')
    data, tracking_sha = load_tracking_candidate(candidate_path)
    source = data['source']
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_does_not_match_tracking_candidate')
    _validate_segments(activity_segments, decoded_seconds(data))
    if (not isinstance(adapters, dict)
            or any(activity not in CONTEXT_TASKS
                   or getattr(adapter, 'task', None) is not CONTEXT_TASKS[activity]
                   or not callable(getattr(adapter, 'analyze', None))
                   for activity, adapter in adapters.items())):
        raise ValueError('invalid_adapter')
    if (type(min_request_interval) not in (int, float) or not 0 <= min_request_interval <= 60
            or type(rate_limit_wait) not in (int, float) or not 0 <= rate_limit_wait <= 300
            or type(max_parallel) is not int or not 1 <= max_parallel <= MAX_PARALLEL):
        raise ValueError('invalid_reading_parameters')
    events = []
    for path in channel_paths:
        reading = reading_for_document(json.loads(Path(path).read_bytes().decode('utf-8')),
                                       source['duration'])
        if (reading['source_sha256'] != source['sha256']
                or reading['tracking_candidate_sha256'] != tracking_sha
                or reading['decoded_seconds'] != decoded_seconds(data)):
            raise ValueError('channel_does_not_match_tracking_candidate')
        events.extend(reading['events'])
    moments, skipped = plan_context_moments(data, events, max_frames=max_frames,
                                            max_moments=max_moments)
    for moment in moments:
        moment['activity'] = activity_at(activity_segments, moment['end_time'])
    if plan_only:
        return {'moments': len(moments), 'skipped': skipped,
                'frames': sum(len(m['frames']) for m in moments),
                'activities': dict(Counter(m['activity'] for m in moments))}
    if type(max_requests) is not int or max_requests < max(1, len(moments)):
        raise ValueError('request_budget_too_small')
    if any(moment['activity'] not in adapters for moment in moments):
        raise ValueError('invalid_adapter')

    reader = frame_reader_factory(video_path)
    images = {}
    try:
        for index in sorted({f['frame_index'] for m in moments for f in m['frames']}):
            images[index] = reader.read(index)
    finally:
        reader.close()
    windows = [build_movement_window(
        m['frames'], [images[f['frame_index']] for f in m['frames']],
        crop_mode='window_stable_others_marked') for m in moments]
    images.clear()

    answers, stats = send_windows(
        moments, windows, lambda moment: adapters[moment['activity']], source['sha256'],
        max_requests=max_requests, min_request_interval=min_request_interval,
        rate_limit_wait=rate_limit_wait, sleep=sleep, progress=progress,
        max_parallel=max_parallel)
    stored = [{key: moment[key] for key in ('moment_id', 'anchors', 'start_time', 'end_time',
                                            'detected_time', 'activity')}
              | {'frame_times': [f['time'] for f in moment['frames']],
                 'status': 'read' if observation else 'unread',
                 'failure': None if observation else failure,
                 'observation': observation}
              for moment, (observation, failure) in zip(moments, answers)]
    requests_used, rate_limit_waits = stats['requests_used'], stats['rate_limit_waits']
    providers, models, failure_codes = stats['providers'], stats['models'], stats['failure_codes']
    if providers - {provider}:
        raise ValueError('provider_not_pinned')
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_changed_during_reading')
    document = {'schema_version': 3, 'kind': 'context_channel_reading',
                'source_sha256': source['sha256'], 'tracking_candidate_sha256': tracking_sha,
                'decoded_seconds': decoded_seconds(data),
                'config': {'model': model, 'provider': provider,
                           'prompt_sha256': dict(PROMPT_SHA256),
                           'max_frames_per_moment': max_frames},
                'activity_segments': [dict(segment) for segment in activity_segments],
                'moments': stored, 'events': context_events(stored)}
    encoded = encode_context_channel_document(document, source['duration'])
    read = sum(m['status'] == 'read' for m in stored)
    report = {'moments': len(stored), 'skipped': skipped, 'read': read,
              'unread': len(stored) - read, 'requests_used': requests_used,
              'rate_limit_waits': rate_limit_waits,
              'failure_codes': dict(sorted(failure_codes.items())),
              'endpoint_providers': sorted(providers), 'resolved_models': sorted(models),
              'external_processing': True, 'frames_sent': sum(len(m['frame_times'])
                                                              for m in stored)}
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_bytes(pending, encoded)
    _write_bytes(report_path, json.dumps(report, ensure_ascii=False, sort_keys=True,
                                         indent=2).encode('utf-8'))
    return report
