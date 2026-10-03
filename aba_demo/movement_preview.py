"""No-provider preview of a movement reading: plan, exact images, pilot sheets, labels.

Builds every eligible window exactly as it would be sent, records only image
hashes and sizes, and renders private review sheets for a stratified pilot set
together with a blank label template. Nothing here reads credentials or opens a
network connection. Outputs contain scene images and must stay outside the
repository.
"""

import io
import json
from pathlib import Path
import statistics

from .colab_workflow import _write_bytes
from .export import file_sha256
from .movement_frames import SequentialFrameReader, build_movement_window
from .movement_schema import MOVEMENT_FIELDS, SEPARABILITY
from .movement_windows import decoded_seconds, load_tracking_candidate, plan_movement_windows


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OVERLAP_BUCKETS = (('below_0.2', 0.0, 0.2), ('0.2_to_0.5', 0.2, 0.5),
                   ('at_least_0.5', 0.5, float('inf')))
MAX_PILOT_WINDOWS = 50
TILE_WIDTH, CROP_HEIGHT, HEADER_HEIGHT = 360, 240, 64


def plan_summary(windows):
    """Counts and seconds per status plus the overlap risk of eligible windows."""
    counts, seconds = {}, {}
    for window in windows:
        status = window['status']
        counts[status] = counts.get(status, 0) + 1
        seconds[status] = seconds.get(status, 0.0) + window['end_time'] - window['start_time']
    eligible = [window for window in windows if window['status'] == 'eligible']
    return {
        'status_counts': dict(sorted(counts.items())),
        'status_seconds': {status: round(value, 3) for status, value in sorted(seconds.items())},
        'eligible_overlap': {name: sum(low <= window['max_other_overlap'] < high
                                       for window in eligible)
                             for name, low, high in OVERLAP_BUCKETS},
        'max_requests_without_retry': len(eligible),
    }


def _bucket(window):
    return next(name for name, low, high in OVERLAP_BUCKETS
                if low <= window['max_other_overlap'] < high)


def _spread(items, count):
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    return [items[round(part * (len(items) - 1) / (count - 1))] for part in range(count)]


def select_pilot_windows(windows, *, count=12, include_times=()):
    """Deterministic pilot: windows covering ``include_times``, then equal overlap strata
    spread across the session. Only eligible windows are chosen."""
    if type(count) is not int or not 1 <= count <= MAX_PILOT_WINDOWS:
        raise ValueError('invalid_pilot_request')
    eligible = [window for window in windows if window['status'] == 'eligible']
    chosen = []
    for time in include_times:
        for window in eligible:
            if window['start_time'] <= time < window['end_time'] and window not in chosen:
                chosen.append(window)
    chosen = chosen[:count]
    strata = {name: [window for window in eligible
                     if _bucket(window) == name and window not in chosen]
              for name, _, _ in OVERLAP_BUCKETS}
    quota = {name: 0 for name in strata}
    remaining = count - len(chosen)
    included = {name: sum(_bucket(window) == name for window in chosen) for name in strata}
    while remaining > 0:
        open_strata = [name for name in strata if quota[name] < len(strata[name])]
        if not open_strata:
            break
        name = min(open_strata, key=lambda key: (included[key] + quota[key],
                                                 [n for n, _, _ in OVERLAP_BUCKETS].index(key)))
        quota[name] += 1
        remaining -= 1
    for name, items in strata.items():
        chosen.extend(_spread(items, quota[name]))
    return sorted(window['segment_id'] for window in chosen)


def labels_template(windows):
    """Blank human labels for the pilot; filled before any model output is seen."""
    vocabulary = {'child_separable': list(SEPARABILITY) + ['not_determinable']}
    for name, values in MOVEMENT_FIELDS.items():
        vocabulary[name] = [value for value in values if value != 'not_observable'] + [
            'not_observable', 'not_determinable']
    return {
        'schema_version': 1, 'kind': 'movement_pilot_labels', 'reviewer': '',
        'labeled_before_model_output': None,
        'instructions': ('Label from the sheets only. Evidence positions refer to the '
                         'numbered columns. Use not_determinable when the frames do not '
                         'allow a judgment. Record any other person whose movement '
                         'could be mistaken for the child in actor_note.'),
        'vocabulary': vocabulary,
        'windows': [{
            'segment_id': window['segment_id'], 'start_time': window['start_time'],
            'end_time': window['end_time'],
            'labels': {'child_separable': None, **dict.fromkeys(MOVEMENT_FIELDS),
                       'actor_note': None},
        } for window in windows],
    }


def render_sheet(window, built):
    """One private PNG: numbered columns of outlined scene over the stable crop."""
    from PIL import Image, ImageDraw

    count = len(built['frames'])
    scene_height = round(TILE_WIDTH * 9 / 16)
    sheet = Image.new('RGB', (TILE_WIDTH * count, HEADER_HEIGHT + scene_height + CROP_HEIGHT + 24),
                      'white')
    draw = ImageDraw.Draw(sheet)
    draw.text((6, 6), (f"{window['segment_id']}  {window['start_time']:.3f}-"
                       f"{window['end_time']:.3f}s  target_id={window['target_id']}  "
                       f"max_other_overlap={window['max_other_overlap']:.2f}"), fill='black')
    draw.text((6, 26), 'frames ' + ', '.join(str(frame['frame_index'])
                                            for frame in window['frames']), fill='black')
    draw.text((6, 44), 'images ' + ' '.join(value[:10] for value in built['image_sha256']),
              fill='black')
    for position, frame in enumerate(built['frames']):
        left = position * TILE_WIDTH
        scene = Image.open(io.BytesIO(frame['scene_jpeg'])).convert('RGB')
        scene.thumbnail((TILE_WIDTH - 8, scene_height))
        sheet.paste(scene, (left + 4, HEADER_HEIGHT))
        crop = Image.open(io.BytesIO(frame['target_crop_jpeg'])).convert('RGB')
        crop.thumbnail((TILE_WIDTH - 8, CROP_HEIGHT))
        sheet.paste(crop, (left + 4, HEADER_HEIGHT + scene_height + 4))
        draw.text((left + 6, HEADER_HEIGHT + scene_height + CROP_HEIGHT + 8),
                  f"position {position}  t={frame['time']:.3f}s", fill='black')
    output = io.BytesIO()
    sheet.save(output, format='PNG')
    return output.getvalue()


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      indent=1).encode('utf-8')


def prepare_preview(video_path, candidate_path, output_dir, *, target_window_seconds=2.0,
                    min_window_seconds=1.0, frames_per_window=4, crop_mode='window_stable',
                    pilot_count=12,
                    include_times=(), frame_reader_factory=SequentialFrameReader,
                    repository_root=REPOSITORY_ROOT):
    """Write the private plan, pilot sheets and label template; return counts only."""
    video_path, output_dir = Path(video_path), Path(output_dir).resolve()
    if output_dir.is_relative_to(Path(repository_root).resolve()):
        raise ValueError('output_inside_repository')
    data, tracking_sha = load_tracking_candidate(candidate_path)
    source_sha = data['source']['sha256']
    if file_sha256(video_path) != source_sha:
        raise ValueError('video_does_not_match_tracking_candidate')
    plan_path = output_dir / 'movement-plan.json'
    labels_path = output_dir / 'labels.template.json'
    if plan_path.exists() or labels_path.exists() or (output_dir / 'sheets').exists():
        raise ValueError('movement_preview_exists')
    windows = plan_movement_windows(
        data, target_window_seconds=target_window_seconds,
        min_window_seconds=min_window_seconds, frames_per_window=frames_per_window)
    pilot_ids = select_pilot_windows(windows, count=pilot_count, include_times=include_times)
    sheets, request_bytes = {}, []
    reader = frame_reader_factory(video_path)
    try:
        for window in windows:
            if window['status'] != 'eligible':
                continue
            images = [reader.read(frame['frame_index']) for frame in window['frames']]
            built = build_movement_window(window['frames'], images, crop_mode=crop_mode)
            window['image_sha256'] = built['image_sha256']
            window['crop_box'] = built['crop_box']
            window['image_bytes'] = sum(len(frame[key]) for frame in built['frames']
                                        for key in ('scene_jpeg', 'target_crop_jpeg'))
            request_bytes.append(window['image_bytes'])
            if window['segment_id'] in pilot_ids:
                sheets[window['segment_id']] = render_sheet(window, built)
    finally:
        reader.close()
    if file_sha256(video_path) != source_sha:
        raise ValueError('video_changed_during_preview')
    summary = plan_summary(windows)
    summary['image_bytes_per_request'] = (
        {'median': statistics.median(request_bytes), 'max': max(request_bytes)}
        if request_bytes else None)
    plan = {
        'schema_version': 1, 'kind': 'movement_plan', 'source_sha256': source_sha,
        'tracking_candidate_sha256': tracking_sha,
        'parameters': {'target_window_seconds': target_window_seconds,
                       'min_window_seconds': min_window_seconds,
                       'frames_per_window': frames_per_window, 'crop_mode': crop_mode},
        'decoded_seconds': decoded_seconds(data), 'summary': summary,
        'pilot_segment_ids': pilot_ids, 'windows': windows,
    }
    pilot_windows = [window for window in windows if window['segment_id'] in pilot_ids]
    (output_dir / 'sheets').mkdir(parents=True)
    _write_bytes(plan_path, _json_bytes(plan))
    _write_bytes(labels_path, _json_bytes(labels_template(pilot_windows)))
    for identifier, png in sheets.items():
        _write_bytes(output_dir / 'sheets' / f'{identifier}.png', png)
    return {'summary': summary, 'pilot_segment_ids': pilot_ids, 'output_dir': str(output_dir)}
