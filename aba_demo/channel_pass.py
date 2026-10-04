"""One forward pass over a recorded session, shared by the local channels.

The posture, large-movement and orientation readers all walk the same 5 Hz
samples of a tracking candidate. Each reader is a *job* with a ``step`` per
sample and a ``finish`` that writes its document. ``run_pass`` decodes every
needed frame once, runs the pose detector at most once per frame, and computes
a camera step at most once per frame pair and estimator, then hands the same
results to every job. A job run alone or with others produces the same bytes.
"""

from pathlib import Path

from .export import file_sha256
from .movement_windows import load_tracking_candidate


class SharedFrame:
    """One sampled frame: decoded on first use, pose detected on first use."""

    def __init__(self, reader, index, detector):
        self.index = index
        self._reader = reader
        self._detector = detector
        self._image = None
        self._detections = None

    @property
    def image(self):
        if self._image is None:
            self._image = self._reader.read(self.index)
        return self._image

    def detections(self):
        if self._detections is None:
            self._detections = self._detector.detect(self.image)
        return self._detections


class PassContext:
    """Camera steps of one sample, computed once per (estimator, previous frame)."""

    def __init__(self):
        self._steps = {}

    def estimate(self, estimator, previous, previous_boxes, frame, boxes):
        # Boxes come from the tracking rows of these two frames, so the indices fix them.
        key = (id(estimator), previous.index, frame.index)
        if key not in self._steps:
            self._steps[key] = estimator.estimate(previous.image, previous_boxes,
                                                  frame.image, boxes)
        return self._steps[key]


def check_output_dir(output_dir, filenames, repository_root, exists_code):
    output_dir = Path(output_dir).resolve()
    if output_dir.is_relative_to(Path(repository_root).resolve()):
        raise ValueError('output_inside_repository')
    if any((output_dir / name).exists() for name in filenames):
        raise ValueError(exists_code)
    return output_dir


def load_bound_candidate(video_path, candidate_path):
    """The quality-passed tracking candidate, bound to these exact video bytes."""
    data, tracking_sha = load_tracking_candidate(candidate_path)
    if file_sha256(video_path) != data['source']['sha256']:
        raise ValueError('video_does_not_match_tracking_candidate')
    return data, tracking_sha


def run_pass(video_path, data, jobs, *, detector, frame_reader_factory, progress=None,
             isolate=False):
    """Feed every sample to every job in time order, then let each job finish.

    With ``isolate`` a job that raises is dropped and its exception is returned in
    its place, so one failing channel does not stop the others; otherwise the
    first error propagates. Problems of the pass itself always propagate.
    """
    frame_of_time = {row['time']: row['frame_index'] for row in data['provenance']['causal_audit']}
    rows = sorted(data['observations'], key=lambda row: row['time'])
    results = [None] * len(jobs)
    active = list(range(len(jobs)))

    def guarded(position, call):
        if not isolate:
            return call()
        try:
            return call()
        except Exception as error:  # one channel's failure stays with that channel
            results[position] = error
            active.remove(position)
            return None

    reader = frame_reader_factory(video_path)
    try:
        previous_index = None
        for number, row in enumerate(rows):
            index = frame_of_time[row['time']]
            if previous_index is not None and index <= previous_index:
                raise ValueError('invalid_tracking_candidate')
            previous_index = index
            frame, context = SharedFrame(reader, index, detector), PassContext()
            for position in tuple(active):
                guarded(position, lambda: jobs[position].step(number, row, index, frame, context))
            if progress and (number + 1) % 100 == 0:
                progress(number + 1, len(rows))
    finally:
        reader.close()
    if file_sha256(video_path) != data['source']['sha256']:
        raise ValueError('video_changed_during_reading')
    for position in tuple(active):
        report = guarded(position, jobs[position].finish)
        if position in active:
            results[position] = report
    return results
