"""Scoring movement readings against labels made before model output was seen."""
import copy
import unittest

from test_movement_schema import SOURCE, TRACKING, provenance, reading_config

FIELDS = ('body_position_change', 'posture_transition', 'hand_arm_movement', 'head_turn')


def segment(number, *, separable='yes', **values):
    from aba_demo.movement_schema import unread_segment

    start = number * 2.0
    times = [start, start + 0.5, start + 1.0]
    result = unread_segment(f'mov-{number:06d}', start, start + 2.0, 'analyzed', target_id=7,
                            max_other_overlap=0.2, sent_frame_times=times,
                            sent_image_sha256=['d' * 64] * 6)
    result['child_separable'] = separable
    for name in FIELDS:
        value = values.get(name, 'not_observable')
        result[name] = value
        result[name + '_evidence_times'] = ([] if value in ('ambiguous', 'not_observable')
                                            else times[:2])
    return result


def document(segments):
    return {'schema_version': 1, 'kind': 'movement_reading', 'source_sha256': SOURCE,
            'tracking_candidate_sha256': TRACKING, 'reading_config': reading_config(),
            'decoded_seconds': 2.0 * len(segments), 'provenance': provenance(),
            'segments': segments}


def labels(windows, origin='human'):
    return {'schema_version': 1, 'kind': 'movement_pilot_labels', 'reviewer': 'reviewer-a',
            'reviewer_origin': origin, 'labeled_before_model_output': True,
            'windows': [{'segment_id': identifier,
                         'labels': {'child_separable': 'yes', 'actor_note': None,
                                    **dict.fromkeys(FIELDS, 'not_determinable'), **values}}
                        for identifier, values in windows]}


class MovementEvalTests(unittest.TestCase):
    def test_outcomes_per_field_and_useful_coverage(self):
        from aba_demo.movement_eval import score_movement

        segments = [segment(0, body_position_change='small', hand_arm_movement='visible'),
                    segment(1, body_position_change='large', head_turn='none_visible'),
                    segment(2)]
        score = score_movement(document(segments), 6.0, labels([
            ('mov-000000', {'body_position_change': 'small', 'hand_arm_movement': 'visible'}),
            ('mov-000001', {'body_position_change': 'small', 'head_turn': 'not_determinable'}),
            ('mov-000002', {'body_position_change': 'none_visible'}),
        ]))
        body = score['fields']['body_position_change']
        self.assertEqual(body, {'agree': 1, 'disagree': 1, 'overclaim': 0, 'abstained': 1,
                                'both_abstain': 0, 'invalid_evidence': 0})
        self.assertEqual(score['fields']['head_turn']['overclaim'], 1)
        self.assertEqual(score['fields']['posture_transition']['both_abstain'], 3)
        self.assertEqual((score['useful_windows'], score['useful_seconds']), (1, 2.0))
        self.assertEqual((score['labeled_windows'], score['read_windows']), (3, 3))
        self.assertEqual(score['attribution_errors'], 0)

    def test_attribution_errors_stop_the_model_prompt_pair(self):
        from aba_demo.movement_eval import score_movement

        segments = [segment(0, body_position_change='small'), segment(1)]
        stop = score_movement(document(segments), 4.0, labels([
            ('mov-000000', {'child_separable': 'no'}), ('mov-000001', {})]))
        self.assertEqual(stop['attribution_errors'], 1)
        self.assertEqual(stop['decision'], 'stop')
        reviewed = score_movement(document(segments), 4.0,
                                  labels([('mov-000000', {'body_position_change': 'small'})]),
                                  review={'mov-000000': {'actor_error': True,
                                                         'invalid_evidence': []}})
        self.assertEqual((reviewed['attribution_errors'], reviewed['decision']), (1, 'stop'))

    def test_field_gate_and_go_or_revise_decision(self):
        from aba_demo.movement_eval import score_movement

        segments = [segment(number, body_position_change='small') for number in range(4)]
        agreed = [(f'mov-{number:06d}', {'body_position_change': 'small'}) for number in range(4)]
        go = score_movement(document(segments), 8.0, labels(agreed))
        self.assertEqual(go['shown_fields'], ['body_position_change'])
        self.assertEqual(go['decision'], 'go')
        invalid = score_movement(document(segments), 8.0, labels(agreed), review={
            'mov-000000': {'actor_error': False, 'invalid_evidence': ['body_position_change']}})
        self.assertEqual(invalid['fields']['body_position_change']['invalid_evidence'], 1)
        self.assertEqual((invalid['shown_fields'], invalid['decision']), ([], 'revise'))
        few = score_movement(document(segments[:2]), 4.0, labels(agreed[:2]))
        self.assertEqual((few['shown_fields'], few['decision']), ([], 'revise'))

    def test_labels_must_precede_output_and_match_read_segments(self):
        from aba_demo.movement_eval import score_movement

        segments = [segment(0, body_position_change='small')]
        good = labels([('mov-000000', {})])
        late = copy.deepcopy(good)
        late['labeled_before_model_output'] = False
        unknown = labels([('mov-000009', {})])
        bad_value = labels([('mov-000000', {'body_position_change': 'still'})])
        extra = copy.deepcopy(good)
        extra['windows'][0]['labels']['attention'] = 'low'
        origin = labels([('mov-000000', {})], origin='model')
        for value in (late, unknown, bad_value, extra, origin):
            with self.subTest(), self.assertRaisesRegex(ValueError, 'invalid_movement_labels'):
                score_movement(document(segments), 2.0, value)
        with self.assertRaisesRegex(ValueError, 'invalid_movement_review'):
            score_movement(document(segments), 2.0, good,
                           review={'mov-000000': {'actor_error': 'no', 'invalid_evidence': []}})


if __name__ == '__main__':
    unittest.main()
