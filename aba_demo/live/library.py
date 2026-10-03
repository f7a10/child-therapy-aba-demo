"""Analysed sessions for review: the library folder, one sub-folder per session.

Each session was analysed earlier (in the app or by the offline scripts) and is
re-validated when loaded: video SHA-256, tracking file and channel bindings. The
review payload holds the whole session at once, for review after the session:
every channel event with its level from the therapist's activity, the moments
they form, how much of the session each channel could measure, and the measured
state bands (e.g. sitting / standing) so a session without events still shows
what was observed. Nothing here analyses video.
"""
import hashlib
import json
import re
import threading
from pathlib import Path

from ..movement_windows import decoded_seconds
from ..session_timeline import build_timeline
from .scenarios import load_session_library, session_id_for

# Sample states that count as measured, per channel document.
MEASURED_STATES = {
    'posture': frozenset({'sitting', 'standing'}),
    'orientation': frozenset({'toward', 'away'}),
    'movement': frozenset({'measured', 'segment_start'}),
}
# Channels whose measured state is shown as bands on the review timeline.
BAND_STATES = {
    'posture': frozenset({'sitting', 'standing'}),
    'orientation': frozenset({'toward', 'away'}),
}
MAX_BANDS = 4000
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


def channel_summary(name, document, decoded):
    """How much of the session the channel measured, and its state bands."""
    if name == 'context':
        moments = document.get('moments', [])
        return {'moments': len(moments),
                'read': sum(moment.get('status') == 'read' for moment in moments)}
    samples = document.get('samples', [])
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
    }


class SessionLibrary:
    """The analysed-session folder. Thread-safe; reloaded after each new analysis."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sessions = {}
        self._payloads = {}
        self.reload()

    def reload(self):
        sessions = {session.id: session for session in load_session_library(self.root)}
        with self._lock:
            self._sessions = sessions
            self._payloads = {}

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

    def review(self, session_id):
        session = self.get(session_id)
        with self._lock:
            cached = self._payloads.get(session_id)
        if cached is None:
            cached = review_payload(session)
            with self._lock:
                self._payloads[session_id] = cached
        return cached

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
            })
        # Newest analyses first; sessions without a date keep their folder order at the end.
        items.sort(key=lambda item: item['created'] or '', reverse=True)
        return items
