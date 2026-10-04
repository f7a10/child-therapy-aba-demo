"""Context v2 pilot: before / during / after notes for the local channels' moments.

Plans each moment from the local channel documents, adds a BEFORE and an AFTER frame
on the same unbroken child binding, and sends each moment ``--repeats`` times to the
explicit model pinned to one provider (strict schema, privacy flags unchanged), to
measure how stable each answer is. Writes private outputs only: validated closed-enum
answers (``pilot.json``) and one evidence sheet per moment (``sheets/``) for human
review. Raw model output and the key are never printed or stored. --plan-only sends
nothing.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read_local_key(path):
    spec = importlib.util.spec_from_file_location(
        'probe_openrouter_context', ROOT / 'scripts' / 'probe_openrouter_context.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_local_key(path)


def plan(video, candidate_path, channel_paths):
    from aba_demo.channel_events import reading_for_document
    from aba_demo.context_channel_reader import plan_context_moments
    from aba_demo.context_v2 import plan_v2_frames
    from aba_demo.export import file_sha256
    from aba_demo.movement_windows import decoded_seconds, load_tracking_candidate

    data, tracking_sha = load_tracking_candidate(candidate_path)
    if file_sha256(video) != data['source']['sha256']:
        raise ValueError('video_does_not_match_tracking_candidate')
    events = []
    for path in channel_paths:
        reading = reading_for_document(json.loads(Path(path).read_bytes().decode('utf-8')),
                                       data['source']['duration'])
        if (reading['source_sha256'] != data['source']['sha256']
                or reading['tracking_candidate_sha256'] != tracking_sha
                or reading['decoded_seconds'] != decoded_seconds(data)):
            raise ValueError('channel_does_not_match_tracking_candidate')
        events.extend(reading['events'])
    kinds = {(event['channel'], event['event_id']): event['kind'] for event in events}
    moments, skipped = plan_context_moments(data, events, max_frames=2)
    planned = []
    for moment in moments:
        roles, frames = plan_v2_frames(data, moment['frames'])
        planned.append({'moment_id': moment['moment_id'], 'start_time': moment['start_time'],
                        'end_time': moment['end_time'],
                        'anchors': [[a['channel'], kinds[(a['channel'], a['event_id'])]]
                                    for a in moment['anchors']],
                        'roles': roles, 'frames': frames})
    return data, planned, skipped


def windows_for(video, planned):
    from aba_demo.movement_frames import SequentialFrameReader, build_movement_window

    reader = SequentialFrameReader(video)
    images = {}
    try:
        for index in sorted({f['frame_index'] for m in planned for f in m['frames']}):
            images[index] = reader.read(index)
    finally:
        reader.close()
    return [build_movement_window(m['frames'], [images[f['frame_index']] for f in m['frames']],
                                  crop_mode='window_stable_others_marked') for m in planned]


def write_sheet(path, moment, window):
    from PIL import Image, ImageDraw

    tiles = []
    for role, frame in zip(moment['roles'], window['frames']):
        tile = Image.open(io.BytesIO(frame['scene_jpeg'])).convert('RGB')
        tile.thumbnail((480, 270))
        tiles.append((f"{role} t={frame['time']:.1f}s", tile))
    sheet = Image.new('RGB', (sum(t.width for _, t in tiles) + 4 * (len(tiles) + 1), 310), 'white')
    draw = ImageDraw.Draw(sheet)
    draw.text((6, 4), f"{moment['moment_id']} {moment['anchors']} "
                      f"{moment['start_time']:.1f}-{moment['end_time']:.1f}s", fill='black')
    left = 4
    for label, tile in tiles:
        sheet.paste(tile, (left, 22))
        draw.text((left + 4, 26 + tile.height), label, fill='black')
        left += tile.width + 4
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main(argv=None):
    from aba_demo.context_v2 import PROMPT_TEMPLATE_SHA256, second_opinion, task_for
    from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

    parser = argparse.ArgumentParser(description='Context v2 pilot (before / during / after)')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--tracking-candidate', type=Path, required=True)
    parser.add_argument('--channel', type=Path, action='append', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--model')
    parser.add_argument('--provider')
    parser.add_argument('--max-requests', type=int)
    parser.add_argument('--parallel', type=int, default=4)
    parser.add_argument('--key-file', type=Path, default=ROOT / '.env')
    arguments = parser.parse_args(argv)
    if Path(arguments.output_dir).resolve().is_relative_to(ROOT):
        parser.error('output must be outside the repository')
    data, planned, skipped = plan(arguments.video, arguments.tracking_candidate,
                                  arguments.channel)
    print('MOMENTS', len(planned), 'SKIPPED', skipped)
    print('LAYOUTS', dict(Counter('/'.join(m['roles']) for m in planned)))
    windows = windows_for(arguments.video, planned)
    for moment, window in zip(planned, windows):
        write_sheet(arguments.output_dir / 'sheets' / f"{moment['moment_id']}.png", moment, window)
    requests = len(planned) * arguments.repeats
    print('REQUESTS_PLANNED', requests, 'FRAMES_PER_REQUEST',
          [len(m['roles']) for m in planned])
    if arguments.plan_only:
        return 0
    if not (arguments.model and arguments.provider and arguments.max_requests):
        parser.error('sending requires --model, --provider and --max-requests')
    if requests > arguments.max_requests:
        parser.error('request budget too small')  # the rest is kept for one retry per answer
    key = _read_local_key(arguments.key_file)
    if key is None:
        print('PROVIDER_ERROR provider_not_configured')
        return 3
    adapters = {tuple(m['roles']): OpenRouterContextAdapter(
        api_key=key, model=arguments.model, max_tokens=8192, task=task_for(m['roles']),
        provider_order=[arguments.provider], reasoning={'effort': 'low', 'exclude': True})
        for m in planned}
    key = None
    source_sha = data['source']['sha256']

    budget = {'left': arguments.max_requests - requests}
    import threading
    lock = threading.Lock()

    def ask(job):
        position, _ = job
        moment, window = planned[position], windows[position]
        for attempt in range(2):
            try:
                result = adapters[tuple(moment['roles'])].analyze(window['frames'],
                                                                  source_sha256=source_sha)
                break
            except OpenRouterContextError as error:
                failure = error.code + (':' + error.detail if error.detail else '')
                with lock:
                    retry = (attempt == 0 and error.code == 'provider_response_invalid'
                             and budget['left'] > 0)
                    if retry:
                        budget['left'] -= 1
                if not retry:
                    return position, None, failure
        provenance = result.get('provenance') or {}
        if provenance.get('endpoint_provider') != arguments.provider:
            return position, None, 'provider_not_pinned'
        return position, dict(result['observation']), None

    jobs = [(position, repeat) for repeat in range(arguments.repeats)
            for position in range(len(planned))]
    with ThreadPoolExecutor(max_workers=max(1, min(arguments.parallel, 4))) as pool:
        answers = list(pool.map(ask, jobs))
    results = []
    for position, moment in enumerate(planned):
        runs = [(observation, failure) for p, observation, failure in answers if p == position]
        results.append({
            'moment_id': moment['moment_id'], 'anchors': moment['anchors'],
            'start_time': moment['start_time'], 'end_time': moment['end_time'],
            'roles': moment['roles'], 'frame_times': [f['time'] for f in moment['frames']],
            'runs': [{'observation': observation, 'failure': failure,
                      'second_opinion': second_opinion([tuple(a) for a in moment['anchors']],
                                                       observation) if observation else None}
                     for observation, failure in runs]})
    out = {'schema': 'context_v2_pilot', 'model': arguments.model, 'provider': arguments.provider,
           'prompt_template_sha256': PROMPT_TEMPLATE_SHA256, 'source_sha256': source_sha,
           'moments': results}
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    (arguments.output_dir / 'pilot.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    failures = Counter(f for _, _, f in answers if f)
    print('READ', sum(1 for _, o, _ in answers if o), 'FAILED', dict(failures))
    for moment in results:
        print(moment['moment_id'], f"{moment['start_time']:.1f}s", moment['anchors'],
              '/'.join(moment['roles']))
        fields = sorted({k for run in moment['runs'] if run['observation']
                         for k in run['observation']})
        for name in fields:
            values = [run['observation'][name] if run['observation'] else '-'
                      for run in moment['runs']]
            print(f'   {name:26s}', values)
        print('   second_opinion            ', [run['second_opinion'] for run in moment['runs']])
    print('PRIVATE_OUTPUT', arguments.output_dir.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
