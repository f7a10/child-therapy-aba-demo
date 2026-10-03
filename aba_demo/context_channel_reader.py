"""Context channel reader: a few frames per locally measured event, sent for closed notes.

Moments come only from events the local channels already produced (posture, large
movement, orientation), each read from 2-4 confirmed-identity samples of the same
tracked child inside the event. Frames are re-decoded from the SHA-verified source;
other tracked people are outlined in red and the child in green. Raw model output is
never stored; only the validated closed-enum observation is kept. Writes a pending,
source- and tracking-bound ``context_channel.pending.json`` outside the repository.
"""

from collections import Counter
import json
import math
from pathlib import Path
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


def read_context(video_path, candidate_path, channel_paths, output_dir, adapters, *,
                 activity_segments, model, provider, max_requests, max_frames=3, max_moments=MAX_MOMENTS,
                 min_request_interval=0.0, rate_limit_wait=0.0,
                 frame_reader_factory=SequentialFrameReader, sleep=clock.sleep,
                 progress=None, plan_only=False, repository_root=REPOSITORY_ROOT):
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
            or type(rate_limit_wait) not in (int, float) or not 0 <= rate_limit_wait <= 300):
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

    stored, providers, models = [], set(), set()
    requests_used = rate_limit_waits = 0
    failure_codes = Counter()
    last_request = None
    for position, (moment, window) in enumerate(zip(moments, windows)):
        remaining = len(moments) - position - 1
        observation, failure, retried = None, None, False
        while True:
            if last_request is not None and min_request_interval:
                sleep(max(0.0, min_request_interval - (clock.monotonic() - last_request)))
            requests_used += 1
            last_request = clock.monotonic()
            try:
                result = adapters[moment['activity']].analyze(
                    window['frames'], source_sha256=source['sha256'])
            except OpenRouterContextError as error:
                can_retry = requests_used + remaining < max_requests
                if (error.code == 'provider_rate_limited' and rate_limit_wait
                        and rate_limit_waits < MAX_RATE_LIMIT_WAITS and can_retry):
                    rate_limit_waits += 1
                    sleep(rate_limit_wait)
                    continue
                if error.code in TERMINAL_PROVIDER_CODES:
                    error.requests_used = requests_used
                    raise
                failure = error.code + (':' + error.detail if error.detail else '')
                failure_codes[failure] += 1
                if error.code == 'provider_response_invalid' and not retried and can_retry:
                    retried = True
                    continue
                break
            if not isinstance(result, dict) or not isinstance(result.get('observation'), dict):
                raise ValueError('invalid_adapter_result')
            observation = dict(result['observation'])
            provenance = result.get('provenance') or {}
            providers.add(str(provenance.get('endpoint_provider')))
            models.add(str(provenance.get('resolved_model')))
            break
        stored.append({key: moment[key] for key in ('moment_id', 'anchors', 'start_time',
                                                    'end_time', 'detected_time', 'activity')}
                      | {'frame_times': [f['time'] for f in moment['frames']],
                         'status': 'read' if observation else 'unread',
                         'failure': None if observation else failure,
                         'observation': observation})
        if progress:
            progress(position + 1, len(moments))
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
