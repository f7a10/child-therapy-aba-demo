"""Build the unified session timeline from measured channels and therapist-set activities.

Activities are given as start-time:activity changes in session order, e.g.
``--activity 0:table --activity 34:movement``; the first must start at 0. The
timeline is written outside the repository and printed as readable lines.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aba_demo.colab_workflow import _write_bytes
from aba_demo.session_timeline import ACTIVITIES, build_timeline, encode_timeline

LABELS = {'sit_to_stand': 'قام من الجلوس', 'stand_to_sit': 'جلس',
          'large_movement': 'حركة كبيرة',
          'turned_away_from_task': 'التفت بعيداً عن المهمة',
          'turned_back_to_task': 'عاد باتجاه المهمة',
          'context_note': 'ملاحظة سياق (مقترح)'}
ACTIVITY_LABELS = {'table': 'طاولة', 'movement': 'حركي', 'break': 'استراحة'}


def _segments(changes, session_end):
    parsed = []
    for change in changes:
        start, _, activity = change.partition(':')
        try:
            parsed.append((float(start), activity))
        except ValueError:
            raise ValueError('invalid_activity_segments') from None
    if any(activity not in ACTIVITIES for _, activity in parsed):
        raise ValueError('invalid_activity_segments')
    bounds = [start for start, _ in parsed] + [session_end]
    return [{'start_time': start, 'end_time': end, 'activity': activity}
            for (start, activity), end in zip(parsed, bounds[1:])]


def _clock(seconds):
    return f'{int(seconds // 60):02d}:{seconds % 60:05.2f}'


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')  # Arabic labels on Windows consoles
    parser = argparse.ArgumentParser(description='Unified session timeline (local)')
    parser.add_argument('--posture', type=Path, required=True)
    parser.add_argument('--orientation', type=Path)
    parser.add_argument('--movement', type=Path)
    parser.add_argument('--context', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--activity', action='append', required=True,
                        help='start_seconds:activity (table, movement, break)')
    arguments = parser.parse_args(argv)
    output = arguments.output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError('output_inside_repository')
    channels = {}
    for name in ('posture', 'orientation', 'movement', 'context'):
        path = getattr(arguments, name)
        if path is not None:
            raw = path.read_bytes()
            channels[name] = (json.loads(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest())
    session_end = channels['posture'][0]['decoded_seconds']
    timeline = build_timeline(channels, _segments(arguments.activity, session_end), session_end)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes(output, encode_timeline(timeline))
    for entry in timeline['entries']:
        marker = 'علامة للمراجعة' if entry['level'] == 'flag' else 'معلومة'
        details = ' '.join(f'{key}={value}' for key, value in sorted(entry['details'].items())
                           if key != 'child_separable')
        print(f"{_clock(entry['start_time'])}  {LABELS[entry['kind']]}  "
              f"[{ACTIVITY_LABELS[entry['activity']]}]  {marker}" + (f'  {details}' if details else ''))
    print('FLAGS', sum(entry['level'] == 'flag' for entry in timeline['entries']))
    print('TIMELINE', output)
    return 0


if __name__ == '__main__':
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
