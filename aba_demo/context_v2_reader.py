"""Context v2 reader: before / during / after notes for the local channels' moments.

Moments come from the local channels' events (grouped as in v1). Each moment gets
up to four frames (``context_v2.plan_v2_frames``): BEFORE, START, END, AFTER, all
on the same unbroken child binding. Frames are re-decoded from the SHA-verified
source, other people outlined in red and the child in green, and sent to the
pinned provider with the strict closed-enum question set of their layout. Raw
model output is never stored. Writes a pending, source- and tracking-bound
``context_channel.pending.json`` (kind ``context_v2_reading``) outside the
repository.
"""

from collections import Counter
import json
from pathlib import Path
import time as clock

from .activities import _validate_segments, activity_at
from .channel_events import reading_for_document
from .colab_workflow import _write_bytes
from .context_channel_reader import MAX_PARALLEL, plan_context_moments, send_windows
from .context_v2 import (
    DOCUMENT_KIND, MAX_FRAMES_PER_MOMENT, MAX_MOMENTS, PROMPT_TEMPLATE_SHA256, SCHEMA_VERSION,
    context_v2_events, encode_context_v2_document, plan_v2_frames, second_opinion, task_for)
from .export import file_sha256
from .movement_frames import SequentialFrameReader, build_movement_window
from .movement_windows import decoded_seconds, load_tracking_candidate

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def read_context_v2(video_path, candidate_path, channel_paths, output_dir, adapter_factory, *,
                    activity_segments, model, provider, max_requests, max_moments=MAX_MOMENTS,
                    min_request_interval=0.0, rate_limit_wait=0.0,
                    frame_reader_factory=SequentialFrameReader, sleep=clock.sleep,
                    progress=None, plan_only=False, max_parallel=1,
                    repository_root=REPOSITORY_ROOT):
    """Read v2 notes; ``adapter_factory(task)`` returns an adapter asking ``task``.

    Returns counts only.
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
    if (type(min_request_interval) not in (int, float) or not 0 <= min_request_interval <= 60
            or type(rate_limit_wait) not in (int, float) or not 0 <= rate_limit_wait <= 300
            or type(max_parallel) is not int or not 1 <= max_parallel <= MAX_PARALLEL
            or not callable(adapter_factory)):
        raise ValueError('invalid_reading_parameters')
    events = []
    for path in channel_paths:
        reading = reading_for_document(json.loads(Path(path).read_bytes().decode('utf-8')),
                                       source['duration'])
        if (reading['source_sha256'] != source['sha256']
                or reading['tracking_candidate_sha256'] != tracking_sha
                or reading['decoded_seconds'] != decoded_seconds(data)):
            raise ValueError('channel_does_not_match_tracking_candidate')
        events.extend(event for event in reading['events'] if event['origin'] == 'measured')
    kinds = {(event['channel'], event['event_id']): event['kind'] for event in events}
    planned, skipped = plan_context_moments(data, events, max_frames=2, max_moments=max_moments)
    moments = []
    for moment in planned:
        try:
            roles, frames = plan_v2_frames(data, moment['frames'])
        except ValueError:
            skipped += 1
            continue
        moments.append({
            'moment_id': f'ctx-{len(moments):06d}',
            'anchors': [{**anchor, 'kind': kinds[(anchor['channel'], anchor['event_id'])]}
                        for anchor in moment['anchors']],
            'start_time': moment['start_time'], 'end_time': moment['end_time'],
            'detected_time': moment['detected_time'],
            'activity': activity_at(activity_segments, moment['end_time']),
            'roles': roles, 'frames': frames})
    if plan_only:
        return {'moments': len(moments), 'skipped': skipped,
                'frames': sum(len(m['frames']) for m in moments),
                'layouts': dict(Counter('/'.join(m['roles']) for m in moments))}
    if type(max_requests) is not int or max_requests < max(1, len(moments)):
        raise ValueError('request_budget_too_small')
    adapters = {}
    for moment in moments:
        layout = tuple(moment['roles'])
        if layout not in adapters:
            task = task_for(layout)
            adapter = adapter_factory(task)
            if getattr(adapter, 'task', None) is not task or not callable(
                    getattr(adapter, 'analyze', None)):
                raise ValueError('invalid_adapter')
            adapters[layout] = adapter

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
        moments, windows, lambda moment: adapters[tuple(moment['roles'])], source['sha256'],
        max_requests=max_requests, min_request_interval=min_request_interval,
        rate_limit_wait=rate_limit_wait, sleep=sleep, progress=progress,
        max_parallel=max_parallel)
    stored = []
    for moment, (observation, failure) in zip(moments, answers):
        anchors = [(a['channel'], a['kind']) for a in moment['anchors']]
        stored.append({key: moment[key] for key in ('moment_id', 'anchors', 'start_time',
                                                    'end_time', 'detected_time', 'activity',
                                                    'roles')}
                      | {'frame_times': [f['time'] for f in moment['frames']],
                         'status': 'read' if observation else 'unread',
                         'failure': None if observation else failure,
                         'observation': observation,
                         'second_opinion': (second_opinion(anchors, observation)
                                            if observation else None)})
    if stats['providers'] - {provider}:
        raise ValueError('provider_not_pinned')
    if file_sha256(video_path) != source['sha256']:
        raise ValueError('video_changed_during_reading')
    document = {'schema_version': SCHEMA_VERSION, 'kind': DOCUMENT_KIND,
                'source_sha256': source['sha256'], 'tracking_candidate_sha256': tracking_sha,
                'decoded_seconds': decoded_seconds(data),
                'config': {'model': model, 'provider': provider,
                           'prompt_template_sha256': PROMPT_TEMPLATE_SHA256,
                           'max_frames_per_moment': MAX_FRAMES_PER_MOMENT},
                'activity_segments': [dict(segment) for segment in activity_segments],
                'moments': stored, 'events': context_v2_events(stored)}
    encoded = encode_context_v2_document(document, source['duration'])
    read = sum(m['status'] == 'read' for m in stored)
    report = {'moments': len(stored), 'skipped': skipped, 'read': read,
              'unread': len(stored) - read, 'requests_used': stats['requests_used'],
              'rate_limit_waits': stats['rate_limit_waits'],
              'failure_codes': dict(sorted(stats['failure_codes'].items())),
              'endpoint_providers': sorted(stats['providers']),
              'resolved_models': sorted(stats['models']),
              'second_opinions': dict(Counter(m['second_opinion'] for m in stored
                                              if m['second_opinion'])),
              'external_processing': True,
              'frames_sent': sum(len(m['frame_times']) for m in stored)}
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_bytes(pending, encoded)
    _write_bytes(report_path, json.dumps(report, ensure_ascii=False, sort_keys=True,
                                         indent=2).encode('utf-8'))
    return report
