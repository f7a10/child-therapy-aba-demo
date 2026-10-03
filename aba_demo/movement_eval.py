"""Score movement readings against labels made before any model output was seen.

Counts only; a small pilot detects gross failure and never establishes accuracy.
``child_separable`` is scored as a model self-report, not trusted as a guarantee.
The optional review records, per read window, whether a claim described another
person's movement (``actor_error``) and which fields cited frames that do not
show the claim (``invalid_evidence``).
"""

import math

from .movement_schema import ABSTAIN, MOVEMENT_FIELDS, SEPARABILITY, validate_movement_document


NOT_DETERMINABLE = 'not_determinable'
LABEL_KEYS = frozenset({'child_separable', 'actor_note', *MOVEMENT_FIELDS})
REVIEW_KEYS = frozenset({'actor_error', 'invalid_evidence'})
OUTCOMES = ('agree', 'disagree', 'overclaim', 'abstained', 'both_abstain', 'invalid_evidence')
MIN_SHOWN_BOTH_CLAIM = 3
MIN_SHOWN_AGREEMENT = 0.8
MAX_SHOWN_OVERCLAIM = 1


def _validate_labels(labels, segments):
    if (not isinstance(labels, dict) or labels.get('schema_version') != 1
            or labels.get('kind') != 'movement_pilot_labels'
            or labels.get('reviewer_origin') not in ('human', 'assistant')
            or labels.get('labeled_before_model_output') is not True
            or not isinstance(labels.get('reviewer'), str) or not labels['reviewer'].strip()
            or not isinstance(labels.get('windows'), list) or not labels['windows']):
        raise ValueError('invalid_movement_labels')
    seen = set()
    for window in labels['windows']:
        values = window.get('labels') if isinstance(window, dict) else None
        identifier = window.get('segment_id') if isinstance(window, dict) else None
        if (identifier not in segments or identifier in seen
                or not isinstance(values, dict) or set(values) != LABEL_KEYS
                or values['child_separable'] not in (*SEPARABILITY, NOT_DETERMINABLE)
                or any(values[name] not in (*allowed, NOT_DETERMINABLE)
                       for name, allowed in MOVEMENT_FIELDS.items())
                or values['actor_note'] is not None and not isinstance(values['actor_note'], str)):
            raise ValueError('invalid_movement_labels')
        seen.add(identifier)


def _validate_review(review, read_ids):
    if not isinstance(review, dict):
        raise ValueError('invalid_movement_review')
    for identifier, entry in review.items():
        if (identifier not in read_ids or not isinstance(entry, dict)
                or set(entry) != REVIEW_KEYS or type(entry['actor_error']) is not bool
                or not isinstance(entry['invalid_evidence'], list)
                or not set(entry['invalid_evidence']) <= set(MOVEMENT_FIELDS)):
            raise ValueError('invalid_movement_review')


def score_movement(document, source_duration, labels, review=None):
    """Return per-field outcomes, attribution errors, useful coverage and a decision."""
    document = validate_movement_document(document, source_duration)
    segments = {segment['segment_id']: segment for segment in document['segments']}
    _validate_labels(labels, segments)
    read_ids = {window['segment_id'] for window in labels['windows']
                if segments[window['segment_id']]['status'] == 'analyzed'}
    review = {} if review is None else review
    _validate_review(review, read_ids)

    fields = {name: dict.fromkeys(OUTCOMES, 0) for name in MOVEMENT_FIELDS}
    attribution_errors = useful_windows = 0
    useful_seconds = 0.0
    for window in labels['windows']:
        identifier = window['segment_id']
        if identifier not in read_ids:
            continue
        segment, label = segments[identifier], window['labels']
        entry = review.get(identifier, {'actor_error': False, 'invalid_evidence': []})
        if entry['actor_error'] or (segment['child_separable'] == 'yes'
                                    and label['child_separable'] == 'no'):
            attribution_errors += 1
        correct = False
        for name in MOVEMENT_FIELDS:
            predicted, expected = segment[name], label[name]
            model_claims = predicted not in ABSTAIN
            label_claims = expected not in ABSTAIN and expected != NOT_DETERMINABLE
            if model_claims and name in entry['invalid_evidence']:
                outcome = 'invalid_evidence'
            elif model_claims and label_claims:
                outcome = 'agree' if predicted == expected else 'disagree'
            elif model_claims:
                outcome = 'overclaim'
            elif label_claims:
                outcome = 'abstained'
            else:
                outcome = 'both_abstain'
            fields[name][outcome] += 1
            correct |= outcome == 'agree'
        if correct:
            useful_windows += 1
            useful_seconds += segment['end_time'] - segment['start_time']

    shown = []
    for name, counts in fields.items():
        both_claim = counts['agree'] + counts['disagree']
        if (both_claim >= MIN_SHOWN_BOTH_CLAIM
                and counts['agree'] >= MIN_SHOWN_AGREEMENT * both_claim
                and counts['overclaim'] <= MAX_SHOWN_OVERCLAIM
                and counts['invalid_evidence'] == 0):
            shown.append(name)
    if attribution_errors:
        decision = 'stop'
    elif any(fields[name]['agree'] >= math.ceil(len(read_ids) / 2) for name in shown):
        decision = 'go'
    else:
        decision = 'revise'
    return {
        'reviewer_origin': labels['reviewer_origin'],
        'labeled_windows': len(labels['windows']), 'read_windows': len(read_ids),
        'attribution_errors': attribution_errors, 'fields': fields,
        'useful_windows': useful_windows, 'useful_seconds': round(useful_seconds, 3),
        'shown_fields': shown, 'decision': decision,
    }
