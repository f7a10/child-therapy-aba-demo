"""Observation-channel events streamed causally into a live or replay session.

The channel documents (posture, large movement, orientation, context) are
validated through ``channel_events`` and bound to the session's video and
tracking file. Each event is released once, when the session's video time
reaches its ``detected_time``; nothing from the future is sent. Its level comes
from the activity the therapist set at the event's end (``session_timeline``
rules), recorded live as the session runs, so the rules live only on the server.
"""

from ..activities import ACTIVITIES
from ..channel_events import channel_reading
from ..session_timeline import level_for

_DUE_TOLERANCE_S = 1e-6


class MomentFeed:
    def __init__(self, documents, source_duration, *, source_sha256, tracking_sha256,
                 activity='table'):
        events = []
        for name, document in sorted(documents.items()):
            reading = channel_reading(name, document, source_duration)
            if (reading['source_sha256'] != source_sha256
                    or reading['tracking_candidate_sha256'] != tracking_sha256):
                raise ValueError('channel_does_not_match_video_or_tracking')
            events.extend(reading['events'])
        self.channels = sorted(documents)
        self._pending = sorted(events, key=lambda e: (e['detected_time'], e['channel'],
                                                      e['event_id']))
        self._activity_changes = []
        self.set_activity(activity, 0.0)

    def set_activity(self, activity, video_time):
        """Record the therapist's activity from ``video_time`` on (None = session start)."""
        if activity not in ACTIVITIES:
            raise ValueError('invalid_activity')
        self._activity_changes.append((0.0 if video_time is None else float(video_time),
                                       activity))

    def _activity_at(self, time):
        current = self._activity_changes[0][1]
        for start, activity in self._activity_changes:
            if start <= time + _DUE_TOLERANCE_S:
                current = activity
        return current

    def due(self, video_time):
        """Entries confirmed at or before ``video_time`` that were not sent yet."""
        released = []
        while self._pending and self._pending[0]['detected_time'] <= video_time + _DUE_TOLERANCE_S:
            event = self._pending.pop(0)
            activity = self._activity_at(event['end_time'])
            released.append({**event, 'entry_id': f"tl-{event['channel']}-{event['event_id']}",
                             'activity': activity,
                             'level': level_for(activity, event['channel'], event['kind'])})
        return released
