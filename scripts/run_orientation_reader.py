"""Local orientation reading: head turned toward / away from a therapist-drawn task region.

Runs a local pose model on the confirmed samples of a reviewed tracking candidate,
writes a pending orientation document outside the repository, and renders one
private evidence sheet per event (the cited before/after frames with the child
outlined in green and the task region in blue). Nothing is sent to any provider.
Prints counts only. The region assumes a fixed camera.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aba_demo.movement_frames import SequentialFrameReader
from aba_demo.orientation_features import valid_task_region
from aba_demo.orientation_reader import YoloPoseDetector, read_orientation


def _default_detector(arguments):
    return YoloPoseDetector(arguments.weights, device=arguments.device)


def task_region(text):
    """Parse ``x1,y1,x2,y2`` normalized to [0, 1]."""
    try:
        region = [float(value) for value in text.split(',')]
    except ValueError:
        raise argparse.ArgumentTypeError('task region must be x1,y1,x2,y2') from None
    if not valid_task_region(region):
        raise argparse.ArgumentTypeError('task region must be x1<x2, y1<y2 inside [0, 1]')
    return region


def render_evidence(video, candidate_path, document, output_dir, frame_reader_factory):
    """Write ``evidence/<event_id>.png``: before/after frames, child box and task region."""
    from PIL import Image, ImageDraw

    data = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    boxes = {row['time']: [box['xyxy'] for box in row['boxes'] if box.get('id') == row['target_id']]
             for row in data['observations'] if row['identity'] == 'confirmed'}
    frames = {sample['time']: sample['frame_index'] for sample in document['samples']}
    region = document['config']['task_region']
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
            draw = ImageDraw.Draw(tile)
            line = max(2, width // 200)
            draw.rectangle((region[0] * width, region[1] * height, region[2] * width,
                            region[3] * height), outline=(0, 120, 255), width=line)
            for x1, y1, x2, y2 in boxes.get(time, []):
                draw.rectangle((x1 * width, y1 * height, x2 * width, y2 * height),
                               outline=(0, 255, 0), width=line)
            tile.thumbnail((640, 360))
            tiles.append((time, tile))
        sheet = Image.new('RGB', (sum(tile.width for _, tile in tiles) + 8, 400), 'white')
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


def main(argv=None, detector_factory=None, frame_reader_factory=SequentialFrameReader,
         motion_estimator_factory=None):
    parser = argparse.ArgumentParser(description='Local orientation reading (no provider)')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--tracking-candidate', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Private directory outside the repository')
    parser.add_argument('--task-region', type=task_region, required=True,
                        help='Normalized x1,y1,x2,y2 drawn by the therapist (fixed camera)')
    parser.add_argument('--weights', type=Path, default=ROOT / 'yolo11s-pose.pt')
    parser.add_argument('--device', default=None)
    arguments = parser.parse_args(argv)
    detector = (detector_factory or _default_detector)(arguments)
    report = read_orientation(arguments.video, arguments.tracking_candidate, arguments.output_dir,
                              task_region=arguments.task_region, detector=detector,
                              motion_estimator=(motion_estimator_factory()
                                                if motion_estimator_factory else None),
                              weights_name=Path(arguments.weights).name,
                              frame_reader_factory=frame_reader_factory,
                              progress=lambda done, total: print(f'PROGRESS {done}/{total}',
                                                                 flush=True))
    document = json.loads((Path(arguments.output_dir) / 'orientation.pending.json')
                          .read_text(encoding='utf-8'))
    render_evidence(arguments.video, arguments.tracking_candidate, document,
                    arguments.output_dir, frame_reader_factory)
    print('STATE_COUNTS', report['state_counts'])
    print('EVENT_COUNTS', report['event_counts'])
    for event in document['events']:
        print('EVENT', event['event_id'], event['kind'],
              f"{event['start_time']:.2f}-{event['end_time']:.2f}s",
              f"detected={event['detected_time']:.2f}s")
    print('ORIENTATION_CANDIDATE_SHA256', report['orientation_candidate_sha256'])
    print('PRIVATE_OUTPUT', Path(arguments.output_dir).resolve())
    return 0


if __name__ == '__main__':
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
