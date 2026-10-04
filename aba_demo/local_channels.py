"""All local channels of a session in one pass over its video.

Posture, large movement and (with a therapist-drawn task region) orientation are
read together: each sampled frame is decoded once, the pose detector runs once per
frame, and the camera step between two frames is estimated once and shared. Every
channel writes the same document it would write alone (``read_posture``,
``read_large_movement``, ``read_orientation``). A channel that fails is reported
on its own; the others still finish. Nothing leaves the machine.
"""

from pathlib import Path

from .channel_pass import check_output_dir, load_bound_candidate, run_pass
from .large_movement_reader import (
    MIN_CAMERA_INLIERS, BackgroundMotionEstimator, LargeMovementJob)
from .large_movement_reader import REPOSITORY_ROOT
from .movement_frames import SequentialFrameReader
from .orientation_features import valid_task_region
from .orientation_reader import OrientationJob
from .posture_reader import PostureJob

JOBS = {'posture': PostureJob, 'movement': LargeMovementJob, 'orientation': OrientationJob}
EXISTS = {'posture': 'posture_candidate_exists',
          'movement': 'large_movement_candidate_exists',
          'orientation': 'orientation_candidate_exists'}
FILENAMES = {name: job.PENDING for name, job in JOBS.items()}


def read_local_channels(video_path, candidate_path, outputs, *, detector, task_region=None,
                        weights_name='yolo11s-pose.pt', motion_estimator=None,
                        frame_reader_factory=SequentialFrameReader, progress=None,
                        repository_root=REPOSITORY_ROOT):
    """``outputs`` maps channel name -> private output folder.

    Returns ``(reports, errors)``: the count report of every channel that finished
    and the exception of every channel that failed.
    """
    if not outputs or set(outputs) - set(JOBS):
        raise ValueError('invalid_channels')
    if 'orientation' in outputs and not valid_task_region(task_region):
        raise ValueError('invalid_task_region')
    folders = {name: check_output_dir(folder, (JOBS[name].PENDING, JOBS[name].REPORT),
                                      repository_root, EXISTS[name])
               for name, folder in outputs.items()}
    data, tracking_sha = load_bound_candidate(video_path, candidate_path)
    # One stateless estimator with the readers' default settings, so camera steps are shared.
    estimator = (motion_estimator if motion_estimator is not None
                 else BackgroundMotionEstimator(min_inliers=MIN_CAMERA_INLIERS))
    names = [name for name in JOBS if name in folders]
    jobs = []
    for name in names:
        options = {'weights_name': weights_name}
        if name != 'posture':
            options['motion_estimator'] = estimator
        if name == 'orientation':
            options['task_region'] = task_region
        jobs.append(JOBS[name](data, tracking_sha, folders[name], **options))
    results = run_pass(Path(video_path), data, jobs, detector=detector,
                       frame_reader_factory=frame_reader_factory, progress=progress,
                       isolate=True)
    reports = {name: result for name, result in zip(names, results)
               if not isinstance(result, Exception)}
    errors = {name: result for name, result in zip(names, results)
              if isinstance(result, Exception)}
    return reports, errors
