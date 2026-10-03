"""Context channel entry point: plan moments locally, then send them for closed notes.

--plan-only counts the moments the local channels' events give, without reading
credentials or contacting a provider. Without it, the moments are sent to the
explicit model, pinned to one provider, under a hard request cap. The key is read
from a local file and never printed; raw model output is never printed or stored.
Prints counts only.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _default_adapter(api_key, model, provider, reasoning, activity):
    from aba_demo.context_channel_schema import CONTEXT_TASKS
    from aba_demo.openrouter_context import OpenRouterContextAdapter

    return OpenRouterContextAdapter(api_key=api_key, model=model, max_tokens=8192,
                                    task=CONTEXT_TASKS[activity], provider_order=[provider],
                                    reasoning=reasoning)


def _segments(changes, session_end):
    """``start:activity`` changes in session order -> segments tiling [0, session_end]."""
    parsed = []
    for change in changes:
        start, _, activity = change.partition(':')
        try:
            parsed.append((float(start), activity))
        except ValueError:
            raise ValueError('invalid_activity_segments') from None
    bounds = [start for start, _ in parsed] + [session_end]
    return [{'start_time': start, 'end_time': end, 'activity': activity}
            for (start, activity), end in zip(parsed, bounds[1:])]


def _read_local_key(path):
    spec = importlib.util.spec_from_file_location(
        'probe_openrouter_context', ROOT / 'scripts' / 'probe_openrouter_context.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_local_key(path)


def main(argv=None, adapter_factory=None, frame_reader_factory=None):
    from aba_demo.activities import ACTIVITIES
    from aba_demo.context_channel_reader import read_context
    from aba_demo.movement_windows import decoded_seconds, load_tracking_candidate
    from aba_demo.openrouter_context import OpenRouterContextError

    parser = argparse.ArgumentParser(description='Context notes for locally measured moments')
    parser.add_argument('--plan-only', action='store_true', help='Count moments; send nothing')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--tracking-candidate', type=Path, required=True)
    parser.add_argument('--channel', type=Path, action='append', required=True,
                        help='Local channel document (posture / large movement / orientation)')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Private directory outside the repository')
    parser.add_argument('--activity', action='append', required=True,
                        help='start_seconds:activity set by the therapist (table, movement, break)')
    parser.add_argument('--max-frames', type=int, default=3)
    parser.add_argument('--max-moments', type=int, default=40)
    parser.add_argument('--model', help='Explicit OpenRouter model ID; no default')
    parser.add_argument('--provider', help='Pinned OpenRouter provider; no fallbacks')
    parser.add_argument('--max-requests', type=int, help='Hard cap including retries')
    parser.add_argument('--reasoning-effort', default='low',
                        choices=['none', 'minimal', 'low', 'medium', 'high'])
    parser.add_argument('--min-request-interval', type=float, default=3.0)
    parser.add_argument('--rate-limit-wait', type=float, default=60.0)
    parser.add_argument('--key-file', type=Path, default=ROOT / '.env')
    arguments = parser.parse_args(argv)
    data, _ = load_tracking_candidate(arguments.tracking_candidate)
    segments = _segments(arguments.activity, decoded_seconds(data))
    options = {'max_frames': arguments.max_frames, 'max_moments': arguments.max_moments,
               'activity_segments': segments,
               'min_request_interval': arguments.min_request_interval,
               'rate_limit_wait': arguments.rate_limit_wait}
    if frame_reader_factory is not None:
        options['frame_reader_factory'] = frame_reader_factory
    if arguments.plan_only:
        from aba_demo.context_channel_schema import CONTEXT_TASKS

        class _NoSend:
            def __init__(self, activity):
                self.task = CONTEXT_TASKS[activity]

            def analyze(self, *args, **kwargs):
                raise AssertionError('plan_only_never_sends')

        report = read_context(arguments.video, arguments.tracking_candidate, arguments.channel,
                              arguments.output_dir, {a: _NoSend(a) for a in ACTIVITIES},
                              model='-', provider='-',
                              max_requests=None, plan_only=True, **options)
        print('MOMENTS', report['moments'])
        print('SKIPPED', report['skipped'])
        print('FRAMES_TO_SEND', report['frames'])
        print('MOMENTS_BY_ACTIVITY', report['activities'])
        return 0
    if arguments.model is None or arguments.provider is None or arguments.max_requests is None:
        parser.error('sending requires --model, --provider and --max-requests')
    try:
        key = _read_local_key(arguments.key_file)
    except ValueError:
        print('PROVIDER_ERROR invalid_config')
        return 3
    if key is None:
        print('PROVIDER_ERROR provider_not_configured')
        return 3
    reasoning = (None if arguments.reasoning_effort == 'none'
                 else {'effort': arguments.reasoning_effort, 'exclude': True})
    try:
        adapters = {activity: (adapter_factory or _default_adapter)(
            key, arguments.model, arguments.provider, reasoning, activity)
            for activity in ACTIVITIES}
        report = read_context(
            arguments.video, arguments.tracking_candidate, arguments.channel,
            arguments.output_dir, adapters, model=arguments.model, provider=arguments.provider,
            max_requests=arguments.max_requests,
            progress=lambda done, total: print(f'PROGRESS {done}/{total}', flush=True),
            **options)
    except OpenRouterContextError as error:
        print('PROVIDER_ERROR', error.code)
        print('REQUESTS_USED', getattr(error, 'requests_used', 0))
        return 3
    finally:
        key = None
    for name in ('moments', 'skipped', 'read', 'unread', 'requests_used', 'rate_limit_waits',
                 'failure_codes', 'endpoint_providers', 'resolved_models', 'frames_sent'):
        print(name.upper(), report[name])
    print('PRIVATE_OUTPUT', Path(arguments.output_dir).resolve())
    return 0


if __name__ == '__main__':
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
