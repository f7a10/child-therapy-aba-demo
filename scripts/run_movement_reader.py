"""Local movement-reader entry point: no-provider preview, then a bounded reading.

--plan-only decodes the authorized source, builds every eligible window exactly
as it would be sent, and writes a private plan, pilot sheets and a blank label
template outside the repository. It never reads credentials or contacts a
provider.

--read sends only the windows chosen from that reviewed plan (its pilot set by
default), with an explicit model and request cap, after checking that the images
still match the plan's hashes. The key is read from a local file and never
printed; raw model output is never printed or stored. Prints counts only.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aba_demo.movement_preview import prepare_preview


def _default_adapter(api_key, model, max_tokens, provider_order=None, reasoning=None,
                     task_name='aba_child_movement'):
    from aba_demo.movement_reader import TASKS
    from aba_demo.openrouter_context import OpenRouterContextAdapter

    return OpenRouterContextAdapter(api_key=api_key, model=model, max_tokens=max_tokens,
                                    task=TASKS[task_name], provider_order=provider_order,
                                    reasoning=reasoning)


def _read_local_key(path):
    spec = importlib.util.spec_from_file_location(
        'probe_openrouter_context', ROOT / 'scripts' / 'probe_openrouter_context.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_local_key(path)


def _plan(arguments):
    report = prepare_preview(
        arguments.video, arguments.tracking_candidate, arguments.output_dir,
        target_window_seconds=arguments.target_window_seconds,
        min_window_seconds=arguments.min_window_seconds,
        frames_per_window=arguments.frames_per_window, crop_mode=arguments.crop_mode,
        pilot_count=arguments.pilot_count, include_times=arguments.include_time)
    summary = report['summary']
    print('STATUS_COUNTS', summary['status_counts'])
    print('STATUS_SECONDS', summary['status_seconds'])
    print('ELIGIBLE_OVERLAP', summary['eligible_overlap'])
    print('MAX_REQUESTS_WITHOUT_RETRY', summary['max_requests_without_retry'])
    print('IMAGE_BYTES_PER_REQUEST', summary['image_bytes_per_request'])
    print('PILOT_SEGMENTS', report['pilot_segment_ids'])
    print('PRIVATE_OUTPUT', report['output_dir'])
    return 0


def _read(arguments, adapter_factory):
    from aba_demo.movement_reader import read_movement
    from aba_demo.movement_windows import load_tracking_candidate
    from aba_demo.openrouter_context import OpenRouterContextError

    plan = json.loads(arguments.plan.read_text(encoding='utf-8'))
    _, tracking_sha = load_tracking_candidate(arguments.tracking_candidate)
    if (plan.get('kind') != 'movement_plan' or plan.get('tracking_candidate_sha256') != tracking_sha):
        raise ValueError('plan_does_not_match_tracking_candidate')
    if arguments.windows == 'pilot':
        segment_ids = list(plan['pilot_segment_ids'])
    else:
        segment_ids = [value.strip() for value in arguments.windows.split(',') if value.strip()]
    expected = {window['segment_id']: window['image_sha256'] for window in plan['windows']
                if window['segment_id'] in segment_ids and 'image_sha256' in window}
    parameters = plan['parameters']
    try:
        key = _read_local_key(arguments.key_file)
    except ValueError:
        key = None
        print('PROVIDER_ERROR invalid_config')
        return 3
    if key is None:
        print('PROVIDER_ERROR provider_not_configured')
        return 3
    try:
        pinned = {'provider_order': arguments.provider} if arguments.provider else {}
        if arguments.fields == 'body':
            pinned['task_name'] = 'aba_child_body_movement'
        if arguments.reasoning_effort != 'none':
            pinned['reasoning'] = {'effort': arguments.reasoning_effort, 'exclude': True}
        adapter = adapter_factory(key, arguments.model, arguments.max_tokens, **pinned)
        report = read_movement(
            arguments.video, arguments.tracking_candidate, arguments.output_dir, adapter,
            segment_ids=segment_ids, max_requests=arguments.max_requests,
            target_window_seconds=parameters['target_window_seconds'],
            min_window_seconds=parameters['min_window_seconds'],
            frames_per_window=parameters['frames_per_window'],
            crop_mode=parameters['crop_mode'],
            expected_image_sha256=expected,
            min_request_interval=arguments.min_request_interval,
            rate_limit_wait=arguments.rate_limit_wait,
            progress=lambda done, total: print(f'PROGRESS {done}/{total}', flush=True))
    except OpenRouterContextError as error:
        print('PROVIDER_ERROR', error.code)
        print('REQUESTS_USED', getattr(error, 'requests_used', 0))
        return 3
    except ValueError as error:
        if str(error) != 'too_many_provider_failures':
            raise
        print('READING_ABORTED too_many_provider_failures')
        print('REQUESTS_USED', error.requests_used)
        print('FAILURE_CODES', error.failure_codes)
        return 4
    finally:
        key = None
    print('STATUS_COUNTS', report['status_counts'])
    print('REQUESTS_USED', report['requests_used'])
    print('INVALID_RETRIES', report['invalid_retries'])
    print('RATE_LIMIT_WAITS', report['rate_limit_waits'])
    print('STOPPED_EARLY', report['stopped_early'])
    print('FAILURE_CODES', report['failure_codes'])
    print('ANALYZED_SECONDS', report['analyzed_seconds'])
    print('MOVEMENT_CANDIDATE_SHA256', report['movement_candidate_sha256'])
    print('PRIVATE_OUTPUT', Path(arguments.output_dir).resolve())
    return 0


def main(argv=None, adapter_factory=None):
    parser = argparse.ArgumentParser(description='Identity-gated VLM movement reader (local)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan-only', action='store_true',
                      help='Preview without any provider request')
    mode.add_argument('--read', action='store_true',
                      help='Send the selected windows of a reviewed plan to the provider')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--tracking-candidate', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Private directory outside the repository')
    parser.add_argument('--target-window-seconds', type=float, default=2.0)
    parser.add_argument('--min-window-seconds', type=float, default=1.0)
    parser.add_argument('--frames-per-window', type=int, default=4)
    parser.add_argument('--crop-mode', default='window_stable_others_marked',
                        choices=['window_stable', 'window_stable_others_marked'])
    parser.add_argument('--pilot-count', type=int, default=12)
    parser.add_argument('--include-time', type=float, action='append', default=[],
                        help='Also put the eligible window covering this time in the pilot')
    parser.add_argument('--plan', type=Path, help='movement-plan.json from --plan-only')
    parser.add_argument('--windows', default='pilot',
                        help="'pilot' or comma-separated segment IDs from the plan")
    parser.add_argument('--model', help='Explicit OpenRouter model ID; no default')
    parser.add_argument('--max-requests', type=int, help='Hard cap including retries')
    parser.add_argument('--fields', default='all', choices=['all', 'body'],
                        help='body asks only whole-body position and posture change')
    parser.add_argument('--reasoning-effort', default='none',
                        choices=['none', 'minimal', 'low', 'medium', 'high'],
                        help='Request this effort with returned reasoning text excluded')
    parser.add_argument('--provider', action='append', default=[],
                        help='Pin an OpenRouter provider (repeatable); no fallbacks either way')
    parser.add_argument('--max-tokens', type=int, default=8192)
    parser.add_argument('--min-request-interval', type=float, default=3.0)
    parser.add_argument('--rate-limit-wait', type=float, default=60.0,
                        help='Seconds to wait after a rate limit before one bounded retry')
    parser.add_argument('--key-file', type=Path, default=ROOT / '.env')
    arguments = parser.parse_args(argv)
    if arguments.plan_only:
        return _plan(arguments)
    if arguments.plan is None or arguments.model is None or arguments.max_requests is None:
        parser.error('--read requires --plan, --model and --max-requests')
    return _read(arguments, adapter_factory or _default_adapter)


if __name__ == '__main__':
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
