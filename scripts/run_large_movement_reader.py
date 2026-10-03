"""Local large-movement reading: compensated body-centre episodes with private evidence.

Runs a local pose model on the confirmed samples of a reviewed tracking candidate,
removes camera motion estimated on the background, writes a pending large-movement
document outside the repository, and renders one private evidence sheet per episode
(the cited frames with the child outlined). Nothing is sent to any provider. Prints
counts and times only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aba_demo.large_movement_reader import BackgroundMotionEstimator, read_large_movement
from aba_demo.movement_frames import SequentialFrameReader
from aba_demo.posture_reader import YoloPoseDetector


def _default_detector(arguments):
    return YoloPoseDetector(arguments.weights, device=arguments.device)


def _default_motion_estimator(arguments):
    return BackgroundMotionEstimator()


def render_evidence(video, candidate_path, document, output_dir, frame_reader_factory):
    """Write ``evidence/<event_id>.png``: the cited frames with the child boxed."""
    from PIL import Image, ImageDraw

    data = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    boxes = {row['time']: [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']]
             for row in data['observations'] if row['identity'] == 'confirmed'}
    frames = {sample['time']: sample['frame_index'] for sample in document['samples']}
    wanted = sorted({time for event in document['events'] for time in event['evidence_times']},
                    key=lambda time: frames[time])
    images = {}
    reader = frame_reader_factory(video)
    try:
        for time in wanted:
            images[time] = reader.read(frames[time]).convert('RGB')
    finally:
        reader.close()
    folder = Path(output_dir) / 'evidence'
    folder.mkdir(parents=True, exist_ok=True)
    for event in document['events']:
        tiles = []
        for time in event['evidence_times']:
            tile = images[time].copy()
            width, height = tile.size
            for x1, y1, x2, y2 in boxes.get(time, []):
                ImageDraw.Draw(tile).rectangle((x1 * width, y1 * height, x2 * width, y2 * height),
                                               outline=(0, 255, 0), width=max(2, width // 200))
            tile.thumbnail((320, 180))
            tiles.append((time, tile))
        sheet = Image.new('RGB', (sum(tile.width for _, tile in tiles) + 8,
                                  max(tile.height for _, tile in tiles) + 56), 'white')
        draw = ImageDraw.Draw(sheet)
        draw.text((6, 6), f"{event['event_id']} {event['kind']} "
                          f"{event['start_time']:.2f}-{event['end_time']:.2f}s (pending review)",
                  fill='black')
        left = 4
        for time, tile in tiles:
            sheet.paste(tile, (left, 32))
            draw.text((left + 4, 32 + tile.height + 2), f't={time:.2f}s', fill='black')
            left += tile.width + 4
        sheet.save(folder / f"{event['event_id']}.png")


def main(argv=None, detector_factory=None, motion_estimator_factory=None,
         frame_reader_factory=SequentialFrameReader):
    parser = argparse.ArgumentParser(description='Local large-movement reading (no provider)')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--tracking-candidate', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Private directory outside the repository')
    parser.add_argument('--weights', type=Path, default=ROOT / 'yolo11s-pose.pt')
    parser.add_argument('--device', default=None)
    arguments = parser.parse_args(argv)
    detector = (detector_factory or _default_detector)(arguments)
    estimator = (motion_estimator_factory or _default_motion_estimator)(arguments)
    report = read_large_movement(
        arguments.video, arguments.tracking_candidate, arguments.output_dir,
        detector=detector, motion_estimator=estimator, weights_name=Path(arguments.weights).name,
        frame_reader_factory=frame_reader_factory,
        progress=lambda done, total: print(f'PROGRESS {done}/{total}', flush=True))
    document = json.loads((Path(arguments.output_dir) / 'large_movement.pending.json')
                          .read_text(encoding='utf-8'))
    render_evidence(arguments.video, arguments.tracking_candidate, document,
                    arguments.output_dir, frame_reader_factory)
    counts = report['state_counts']
    confirmed = sum(count for state, count in counts.items() if state != 'identity_uncertain')
    share = counts.get('not_measurable', 0) / confirmed if confirmed else 0.0
    print('STATE_COUNTS', counts)
    print('NOT_MEASURABLE_SHARE', f'{share:.3f}')
    print('EVENT_COUNTS', report['event_counts'])
    for event in document['events']:
        print('EVENT', event['event_id'], event['kind'],
              f"{event['start_time']:.2f}-{event['end_time']:.2f}s",
              f"detected {event['detected_time']:.2f}s")
    print('LARGE_MOVEMENT_CANDIDATE_SHA256', report['large_movement_candidate_sha256'])
    print('PRIVATE_OUTPUT', Path(arguments.output_dir).resolve())
    return 0


if __name__ == '__main__':
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
