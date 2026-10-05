"""Analysed sessions for review: the library folder, one sub-folder per session.

Each session was analysed earlier (in the app or by the offline scripts) and is
re-validated when loaded: video SHA-256, tracking file and channel bindings. The
review payload holds the whole session at once, for review after the session:
every channel event with its level from the therapist's activity, the moments
they form, how much of the session each channel could measure, and the measured
state bands (e.g. sitting / standing) so a session without events still shows
what was observed. Nothing here analyses video.

The therapist's own review of each moment (confirmed / not seen / unsure, and
a short note) is kept next to the session in ``clinician_review.json``. It is
bound to the video and channel bytes it was given for, never changes a channel
document, and is dropped if the session it was written for no longer matches.
"""
import hashlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from ..large_movement_features import motion_states
from ..movement_windows import decoded_seconds
from ..session_timeline import build_timeline
from .scenarios import load_session_library, session_id_for

# Sample states that count as measured, per channel document.
MEASURED_STATES = {
    'posture': frozenset({'sitting', 'standing', 'lying'}),
    'orientation': frozenset({'toward', 'away'}),
    'movement': frozenset({'measured', 'segment_start'}),
}
# Channels whose measured state is shown as bands on the review timeline.
BAND_STATES = {
    'posture': frozenset({'sitting', 'standing', 'lying'}),
    'orientation': frozenset({'toward', 'away'}),
}
AREA_STATES = frozenset({'at_area', 'away_from_area'})
MAX_BANDS = 4000
REVIEW_NAME = 'clinician_review.json'
REVIEW_KIND = 'clinician_review'
REVIEW_SCHEMA_VERSION = 1
VERDICTS = frozenset({'confirmed', 'not_seen', 'unsure'})
MAX_NOTE_LENGTH = 500
THUMBNAIL_WIDTH = 320
# Where the library card's still frame is taken, as a fraction of the session (past any dark opening).
THUMBNAIL_AT = 0.15
_FOLDER_CHARACTERS = re.compile(r'[^A-Za-z0-9]+')


def _bands(samples, end, states):
    """Consecutive samples in the same shown state -> [start, end, state] bands."""
    bands = []
    for index, sample in enumerate(samples):
        state = sample.get('state')
        if state not in states:
            continue
        stop = samples[index + 1]['time'] if index + 1 < len(samples) else end
        if bands and bands[-1][2] == state and abs(bands[-1][1] - sample['time']) < 1e-6:
            bands[-1][1] = stop
        else:
            bands.append([sample['time'], stop, state])
    return bands[:MAX_BANDS]


def _runs(samples, end, labels):
    """Consecutive samples with the same non-None label -> [start, end, label] runs."""
    runs = []
    for index, (sample, label) in enumerate(zip(samples, labels)):
        if label is None:
            continue
        stop = samples[index + 1]['time'] if index + 1 < len(samples) else end
        if runs and runs[-1][2] == label and abs(runs[-1][1] - sample['time']) < 1e-6:
            runs[-1][1] = stop
        else:
            runs.append([sample['time'], stop, label])
    return runs[:MAX_BANDS]


def _gap_reason(name, sample):
    """Why a sample shows no reading, as a short code for the review page."""
    if sample.get('identity') != 'confirmed':
        return 'identity'
    if name == 'posture':
        return sample.get('reason') or ('unclear' if sample.get('state') == 'unclear' else None)
    if name == 'orientation':
        return 'camera' if sample.get('area_state') == 'not_measurable' else 'unclear'
    return 'no_pose' if sample.get('state') == 'not_measurable' else None


def _shares(labels, total):
    counts = {}
    for label in labels:
        if label is not None:
            counts[label] = counts.get(label, 0) + 1
    return {label: count / total for label, count in sorted(counts.items())}


def _summary_v2(name, document, decoded):
    """Bands, inferred time and the reason behind every gap (newer readings)."""
    samples = document['samples']
    total = len(samples)
    if name == 'posture':
        shown = [s['state'] if s['state'] in MEASURED_STATES['posture']
                 else (f"held_{s['held']}" if s.get('held') else None) for s in samples]
        measured = sum(s['state'] in MEASURED_STATES['posture'] for s in samples)
        summary = {'coverage': measured / total, 'held': sum(bool(s.get('held')) for s in samples) / total}
    elif name == 'orientation':
        shown = [s['area_state'] if s['area_state'] in AREA_STATES else None for s in samples]
        summary = {'coverage': sum(label is not None for label in shown) / total,
                   'head_coverage': sum(s['state'] in MEASURED_STATES['orientation'] for s in samples) / total}
    else:
        shown = motion_states(samples)
        summary = {'coverage': sum(s['state'] in MEASURED_STATES['movement'] for s in samples) / total}
    gaps = [None if label is not None else _gap_reason(name, sample)
            for sample, label in zip(samples, shown)]
    summary.update(bands=_runs(samples, decoded, shown), gaps=_runs(samples, decoded, gaps),
                   reasons=_shares(gaps, total))
    return summary


def channel_summary(name, document, decoded):
    """How much of the session the channel measured, and its state bands."""
    if name == 'context':
        moments = document.get('moments', [])
        return {'moments': len(moments),
                'read': sum(moment.get('status') == 'read' for moment in moments)}
    samples = document.get('samples', [])
    # Newer readings carry what the review needs (held posture, work area, body centre).
    if samples and any(key in samples[0] for key in ('held', 'area_state', 'centre')):
        return _summary_v2(name, document, decoded)
    measured = sum(sample.get('state') in MEASURED_STATES[name] for sample in samples)
    summary = {'coverage': measured / len(samples) if samples else 0.0}
    if name in BAND_STATES:
        summary['bands'] = _bands(samples, decoded, BAND_STATES[name])
    return summary


def review_payload(scenario):
    """The whole analysed session for the review page (all events, not causal)."""
    data = json.loads(scenario.observations.read_bytes().decode('utf-8'))
    duration = data['source']['duration']
    decoded = decoded_seconds(data)
    quality = data.get('provenance', {}).get('quality', {})
    channels = {}
    for name, path in scenario._channel_files.items():
        raw = path.read_bytes()
        channels[name] = (json.loads(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest())
    if channels:  # the channels are bound to one decoded span (checked by build_timeline)
        decoded = next(iter(channels.values()))[0]['decoded_seconds']
    segments = [{'start_time': 0.0, 'end_time': decoded, 'activity': scenario.activity}]
    timeline = (build_timeline(channels, segments, duration) if channels
                else {'entries': [], 'groups': []})
    uncertain = quality.get('uncertain_fraction')
    return {
        'id': scenario.id, 'title': scenario.title, 'activity': scenario.activity,
        'created': scenario.created, 'duration': duration, 'decoded_seconds': decoded,
        'child_confirmed_fraction': (1.0 - uncertain) if isinstance(uncertain, (int, float)) else None,
        'channels': sorted(channels), 'skipped': dict(scenario.skipped),
        'summary': {name: channel_summary(name, document, decoded)
                    for name, (document, _) in channels.items()},
        'entries': timeline['entries'], 'groups': timeline['groups'],
        'binding': {'source_sha256': scenario._digest,
                    'channels': {name: sha for name, (_, sha) in sorted(channels.items())}},
    }


def _valid_mark(mark):
    return (isinstance(mark, dict) and set(mark) == {'verdict', 'note', 'updated'}
            and mark['verdict'] in VERDICTS and isinstance(mark['note'], str)
            and len(mark['note']) <= MAX_NOTE_LENGTH and isinstance(mark['updated'], str))


def read_clinician_review(path, binding, moment_ids):
    """The therapist's marks for this exact session, by moment id ({} if none or stale)."""
    try:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if (not isinstance(document, dict) or document.get('kind') != REVIEW_KIND
            or document.get('schema_version') != REVIEW_SCHEMA_VERSION
            or document.get('binding') != binding or not isinstance(document.get('moments'), dict)):
        return {}
    return {key: mark for key, mark in document['moments'].items()
            if key in moment_ids and _valid_mark(mark)}


def thumbnail_jpeg(video, at_seconds, width=THUMBNAIL_WIDTH):
    """One small JPEG still of the video, or None if the frame cannot be read."""
    import cv2

    capture = cv2.VideoCapture(str(video))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, at_seconds) * 1000.0)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        return None
    height = max(1, round(frame.shape[0] * width / frame.shape[1]))
    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return data.tobytes() if ok else None


class SessionLibrary:
    """The analysed-session folder. Thread-safe; reloaded after each new analysis."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sessions = {}
        self._payloads = {}
        self._thumbnails = {}
        self._review_lock = threading.Lock()
        self.reload()

    def reload(self):
        sessions = {session.id: session for session in load_session_library(self.root)}
        with self._lock:
            self._sessions = sessions
            self._payloads = {}
            self._thumbnails = {}

    def new_folder(self, title, stamp):
        """A fresh, empty session folder named after the title and a timestamp."""
        name = _FOLDER_CHARACTERS.sub('-', title).strip('-')[:40] or 'session'
        folder = self.root / f'{stamp}-{name}'
        number = 1
        while folder.exists():
            number += 1
            folder = self.root / f'{stamp}-{name}-{number}'
        folder.mkdir(parents=True)
        return folder

    @staticmethod
    def id_for_folder(folder):
        return session_id_for(Path(folder))

    def get(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _payload(self, session_id):
        session = self.get(session_id)
        with self._lock:
            cached = self._payloads.get(session_id)
        if cached is None:
            cached = review_payload(session)
            with self._lock:
                self._payloads[session_id] = cached
        return session, cached

    def review(self, session_id):
        """The review payload plus the therapist's marks so far (read fresh each time)."""
        session, payload = self._payload(session_id)
        return {**payload, 'clinician': self._marks(session, payload)}

    @staticmethod
    def _moment_ids(payload):
        # A moment is named by its first entry, which stays the same while its channel files do.
        return {group['entry_ids'][0] for group in payload['groups']}

    def _marks(self, session, payload):
        if session.folder is None:
            return {}
        return read_clinician_review(session.folder / REVIEW_NAME, payload['binding'],
                                     self._moment_ids(payload))

    def mark(self, session_id, moment_id, verdict, note=''):
        """Record (or clear, with verdict None) the therapist's view of one moment."""
        session, payload = self._payload(session_id)
        if session.folder is None:
            raise ValueError('review_not_stored')
        if moment_id not in self._moment_ids(payload):
            raise KeyError(moment_id)
        note = (note or '').strip()
        if verdict is not None and verdict not in VERDICTS:
            raise ValueError('invalid_verdict')
        if len(note) > MAX_NOTE_LENGTH:
            raise ValueError('note_too_long')
        if verdict is None and note:
            raise ValueError('note_needs_verdict')
        with self._review_lock:
            marks = self._marks(session, payload)
            if verdict is None:
                marks.pop(moment_id, None)
            else:
                marks[moment_id] = {'verdict': verdict, 'note': note,
                                    'updated': datetime.now().isoformat(timespec='seconds')}
            document = {'kind': REVIEW_KIND, 'schema_version': REVIEW_SCHEMA_VERSION,
                        'session_id': session_id, 'binding': payload['binding'],
                        'moments': dict(sorted(marks.items()))}
            path = session.folder / REVIEW_NAME
            partial = path.with_suffix('.partial')
            partial.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(partial, path)
        return marks

    def thumbnail(self, session_id):
        """A small still of the session's video for the library list (kept in memory)."""
        session, payload = self._payload(session_id)
        with self._lock:
            cached = self._thumbnails.get(session_id)
        if cached is None:
            cached = thumbnail_jpeg(session.video_path(), payload['decoded_seconds'] * THUMBNAIL_AT) or b''
            with self._lock:
                self._thumbnails[session_id] = cached
        return cached or None

    def list(self):
        with self._lock:
            sessions = list(self._sessions.values())
        items = []
        for session in sessions:
            payload = self.review(session.id)
            items.append({
                'id': session.id, 'title': session.title, 'activity': session.activity,
                'created': session.created, 'duration': payload['duration'],
                'channels': payload['channels'], 'moments': len(payload['groups']),
                'flags': sum(group['level'] == 'flag' for group in payload['groups']),
                'reviewed': len(payload['clinician']),
            })
        # Newest analyses first; sessions without a date keep their folder order at the end.
        items.sort(key=lambda item: item['created'] or '', reverse=True)
        return items
