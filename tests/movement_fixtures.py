"""Synthetic tracking candidates shaped like ReviewSession output (no real data)."""

TARGET_BOX = [0.1, 0.2, 0.4, 0.9]
OTHER_BOX = [0.3, 0.1, 0.7, 0.9]


def candidate(source_sha, *, decoded=60, fps=10.0, uncertain=(), switch_at=None,
              sample_every=5, passed=True, target_box=TARGET_BOX, other_box=OTHER_BOX):
    """Dense causal audit plus sampled observations with target and one other box."""
    audit, observations = [], []
    for index in range(decoded):
        confirmed = index not in uncertain
        target = 7 if switch_at is None or index < switch_at else 9
        time = index / fps
        audit.append({'frame_index': index, 'time': time,
                      'identity': 'confirmed' if confirmed else 'uncertain',
                      'target_id': target, 'selection_event': index in (0, switch_at),
                      'reason': None if confirmed else 'target_lost_reselect'})
        if index % sample_every == 0:
            boxes = [{'id': 3, 'xyxy': list(other_box)}]
            if confirmed:
                boxes.insert(0, {'id': target, 'xyxy': list(target_box)})
            observations.append({
                'time': time, 'identity': 'confirmed' if confirmed else 'uncertain',
                'target_id': target, 'values': {}, 'boxes': boxes,
                'signals': dict.fromkeys(('orientation', 'body_motion', 'out_of_seat',
                                          'hand_motion', 'posture_change')),
            })
    return {
        'schema_version': 1, 'mode': 'precomputed',
        'source': {'name': 'authorized.mp4', 'sha256': source_sha,
                   'duration': (decoded + 1) / fps, 'fps': fps,
                   'frame_count': decoded + 1, 'decoded_frame_count': decoded,
                   'trailing_unreadable_frames': 1, 'analysis_mode': 'precomputed'},
        'provenance': {'sha256': source_sha, 'analysis_mode': 'precomputed',
                       'quality': {'passed': passed}, 'causal_audit': audit},
        'observations': observations,
    }
