"""Strict contract tests for VLM readings of the selected child's visible movement."""
import json
import unittest


def output(**overrides):
    value = {
        'child_separable': 'yes',
        'body_position_change': 'small',
        'body_position_change_frames': [0, 2],
        'posture_transition': 'none_visible',
        'posture_transition_frames': [0, 1, 2],
        'hand_arm_movement': 'not_observable',
        'hand_arm_movement_frames': [],
        'head_turn': 'ambiguous',
        'head_turn_frames': [],
    }
    value.update(overrides)
    return json.dumps(value)


class MovementOutputSchemaTests(unittest.TestCase):
    def test_schema_is_closed_and_limits_evidence_to_supplied_positions(self):
        from aba_demo.movement_schema import MOVEMENT_FIELDS, model_output_schema

        self.assertEqual(list(MOVEMENT_FIELDS), [
            'body_position_change', 'posture_transition', 'hand_arm_movement', 'head_turn'])
        result = model_output_schema(3)
        self.assertFalse(result['additionalProperties'])
        self.assertEqual(result['required'], [
            'child_separable',
            'body_position_change', 'body_position_change_frames',
            'posture_transition', 'posture_transition_frames',
            'hand_arm_movement', 'hand_arm_movement_frames',
            'head_turn', 'head_turn_frames',
        ])
        self.assertEqual(set(result['properties']), set(result['required']))
        for name in MOVEMENT_FIELDS:
            evidence = result['properties'][name + '_frames']
            self.assertEqual(evidence['items'], {'type': 'integer', 'enum': [0, 1, 2]})
            self.assertEqual((evidence['maxItems'], evidence['uniqueItems']), (3, True))
        self.assertEqual(result['properties']['child_separable']['enum'],
                         ['yes', 'no', 'ambiguous', 'not_observable'])
        for bad in (0, 1, 5, True, 2.0, None):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'invalid_movement_input'):
                model_output_schema(bad)

    def test_vocabulary_has_no_interpretive_or_repetition_labels(self):
        from aba_demo.movement_schema import MOVEMENT_FIELDS

        values = {value for allowed in MOVEMENT_FIELDS.values() for value in allowed}
        for forbidden in ('still', 'none', 'minimal', 'repetitive', 'handles_material',
                          'attention', 'hyperactive', 'gaze'):
            self.assertNotIn(forbidden, values)
        for allowed in MOVEMENT_FIELDS.values():
            self.assertEqual(allowed[0], 'none_visible')
            self.assertEqual(allowed[-2:], ('ambiguous', 'not_observable'))


class MovementOutputParserTests(unittest.TestCase):
    times = [20.123456789, 20.623456789, 21.123456789]

    def test_parser_maps_each_field_evidence_to_exact_supplied_times(self):
        from aba_demo.movement_schema import parse_movement_output

        self.assertEqual(parse_movement_output(output(), self.times), {
            'child_separable': 'yes',
            'body_position_change': 'small',
            'body_position_change_evidence_times': [20.123456789, 21.123456789],
            'posture_transition': 'none_visible',
            'posture_transition_evidence_times': list(self.times),
            'hand_arm_movement': 'not_observable',
            'hand_arm_movement_evidence_times': [],
            'head_turn': 'ambiguous',
            'head_turn_evidence_times': [],
        })

    def test_claims_need_two_ordered_frames_and_abstentions_carry_none(self):
        from aba_demo.movement_schema import parse_movement_output

        cases = [
            output(body_position_change_frames=[]),
            output(body_position_change_frames=[1]),
            output(posture_transition='sit_to_stand', posture_transition_frames=[2]),
            output(body_position_change_frames=[2, 0]),
            output(body_position_change_frames=[0, 0]),
            output(body_position_change_frames=[0, 3]),
            output(body_position_change_frames=[True, 2]),
            output(body_position_change_frames=[0.0, 2]),
            output(head_turn_frames=[0, 1]),
            output(hand_arm_movement_frames=[1, 2]),
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'invalid_movement_output'):
                parse_movement_output(raw, self.times)

    def test_rejections_name_the_rule_and_field_without_model_text(self):
        from aba_demo.movement_schema import parse_movement_output

        cases = {
            output(head_turn='visible', head_turn_frames=[1]): 'needs_two_frames:head_turn',
            output(hand_arm_movement_frames=[1, 2]): 'abstain_with_evidence:hand_arm_movement',
            output(child_separable='no'): 'claim_without_separable_child:body_position_change',
            output(body_position_change='jumping'): 'value:body_position_change',
            output(body_position_change_frames=[2, 0]): 'evidence_order:body_position_change',
            output(body_position_change_frames=[0, 7]): 'evidence_position:body_position_change',
            output(child_separable='maybe'): 'value:child_separable',
            'not json': 'json', json.dumps({'child_separable': 'yes'}): 'keys',
        }
        for raw, reason in cases.items():
            with self.subTest(reason=reason), self.assertRaises(ValueError) as caught:
                parse_movement_output(raw, self.times)
            self.assertEqual(str(caught.exception), 'invalid_movement_output:' + reason)

    def test_a_field_subset_asks_only_those_fields_and_abstains_on_the_rest(self):
        from aba_demo.movement_schema import model_output_schema, parse_movement_output

        body = ('body_position_change', 'posture_transition')
        schema = model_output_schema(3, fields=body)
        self.assertEqual(schema['required'], [
            'child_separable', 'body_position_change', 'body_position_change_frames',
            'posture_transition', 'posture_transition_frames'])
        raw = json.dumps({'child_separable': 'yes', 'body_position_change': 'small',
                          'body_position_change_frames': [0, 2],
                          'posture_transition': 'none_visible',
                          'posture_transition_frames': [0, 1]})
        parsed = parse_movement_output(raw, self.times, fields=body)
        self.assertEqual(parsed['body_position_change_evidence_times'],
                         [self.times[0], self.times[2]])
        for name in ('hand_arm_movement', 'head_turn'):
            self.assertEqual((parsed[name], parsed[name + '_evidence_times']),
                             ('not_observable', []))
        with self.assertRaisesRegex(ValueError, 'invalid_movement_output:keys'):
            parse_movement_output(output(), self.times, fields=body)
        for fields in ((), ('attention',), ('head_turn', 'head_turn'), 'head_turn'):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, 'invalid_movement_input'):
                model_output_schema(3, fields=fields)

    def test_non_separable_child_forces_every_field_to_abstain(self):
        from aba_demo.movement_schema import parse_movement_output

        abstaining = output(child_separable='ambiguous',
                            body_position_change='not_observable', body_position_change_frames=[],
                            posture_transition='ambiguous', posture_transition_frames=[])
        self.assertEqual(parse_movement_output(abstaining, self.times)['child_separable'],
                         'ambiguous')
        for separable in ('no', 'ambiguous', 'not_observable'):
            with self.subTest(separable=separable), \
                    self.assertRaisesRegex(ValueError, 'invalid_movement_output'):
                parse_movement_output(output(child_separable=separable), self.times)

    def test_parser_rejects_malformed_extra_or_interpretive_output(self):
        from aba_demo.movement_schema import parse_movement_output

        extra = json.loads(output())
        extra['attention'] = 'low'
        missing = json.loads(output())
        del missing['head_turn_frames']
        cases = [
            output(body_position_change='hyperactive'), output(child_separable='maybe'),
            json.dumps(extra), json.dumps(missing), json.dumps([]),
            '{"child_separable":"yes","child_separable":"yes"}',
            'not json', '', 'x' * 9000, None,
        ]
        for raw in cases:
            with self.subTest(raw=str(raw)[:40]), \
                    self.assertRaisesRegex(ValueError, 'invalid_movement_output'):
                parse_movement_output(raw, self.times)

    def test_supplied_times_must_be_two_to_four_increasing_finite_values(self):
        from aba_demo.movement_schema import parse_movement_output

        for times in ([1.0], [2.0, 1.0], [1.0, 1.0], [0.0, float('nan')], [-1.0, 1.0],
                      [0, 1, 2, 3, 4], [True, 2.0], (1.0, 2.0)):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'invalid_movement_input'):
                parse_movement_output(output(body_position_change_frames=[0, 1],
                                             posture_transition_frames=[0, 1]), times)


SOURCE = 'a' * 64
TRACKING = 'b' * 64


def provenance():
    return {'adapter': 'openrouter', 'source_sha256': SOURCE,
            'requested_model': 'vendor/model', 'resolved_model': 'vendor/model',
            'endpoint_provider': 'fixture-provider', 'external_processing': True,
            'structured_outputs': True, 'data_collection': 'deny',
            'zero_data_retention_required': False,
            'sent_fields': ['scene_jpeg', 'target_crop_jpeg', 'timestamps', 'target_box'],
            'consent': {'required': False, 'granted': False, 'source_sha256': None}}


def reading_config():
    return {'task': 'aba_child_movement', 'prompt_sha256': 'c' * 64,
            'target_window_seconds': 2.0, 'min_window_seconds': 1.0,
            'frames_per_window': 4, 'crop_mode': 'window_stable'}


def analyzed(segment_id, start, end, **overrides):
    times = [start, start + 0.5, start + 1.0]
    segment = {
        'segment_id': segment_id, 'start_time': start, 'end_time': end,
        'status': 'analyzed', 'target_id': 7, 'max_other_overlap': 0.25,
        'sent_frame_times': times, 'sent_image_sha256': ['d' * 64] * 6,
        'child_separable': 'yes',
        'body_position_change': 'large',
        'body_position_change_evidence_times': [times[0], times[2]],
        'posture_transition': 'none_visible',
        'posture_transition_evidence_times': [times[0], times[1]],
        'hand_arm_movement': 'not_observable', 'hand_arm_movement_evidence_times': [],
        'head_turn': 'ambiguous', 'head_turn_evidence_times': [],
        'clinician_confirmation': 'pending',
    }
    segment.update(overrides)
    return segment


def document(segments, *, prov='default', decoded_seconds=4.0):
    return {'schema_version': 1, 'kind': 'movement_reading', 'source_sha256': SOURCE,
            'tracking_candidate_sha256': TRACKING, 'reading_config': reading_config(),
            'decoded_seconds': decoded_seconds,
            'provenance': provenance() if prov == 'default' else prov, 'segments': segments}


class MovementSegmentTests(unittest.TestCase):
    def test_unread_segments_fully_abstain_and_carry_no_reading(self):
        from aba_demo.movement_schema import unread_segment, validate_movement_segment

        uncertain = unread_segment('mov-000001', 2.0, 4.0, 'identity_uncertain')
        self.assertEqual(validate_movement_segment(uncertain, 10.0), uncertain)
        self.assertIsNone(uncertain['target_id'])
        skipped = unread_segment('mov-000002', 4.0, 6.0, 'not_requested',
                                 target_id=7, max_other_overlap=0.4)
        self.assertEqual(validate_movement_segment(skipped, 10.0)['status'], 'not_requested')
        failed = unread_segment('mov-000003', 6.0, 8.0, 'provider_failed', target_id=7,
                                max_other_overlap=0.1, sent_frame_times=[6.0, 7.0],
                                sent_image_sha256=['e' * 64] * 4)
        self.assertEqual(validate_movement_segment(failed, 10.0)['sent_frame_times'], [6.0, 7.0])
        bad = [
            {**uncertain, 'body_position_change': 'none_visible'},
            {**uncertain, 'child_separable': 'yes'},
            {**uncertain, 'head_turn_evidence_times': [2.5]},
            {**uncertain, 'target_id': 7},
            {**uncertain, 'status': 'guess'},
            {**skipped, 'target_id': None},
            {**skipped, 'max_other_overlap': None},
            {**skipped, 'sent_frame_times': [4.0, 5.0]},
            {**failed, 'sent_image_sha256': ['e' * 64] * 3},
            {**failed, 'sent_frame_times': []},
        ]
        for segment in bad:
            with self.subTest(segment=segment), \
                    self.assertRaisesRegex(ValueError, 'invalid_movement_segment'):
                validate_movement_segment(segment, 10.0)

    def test_analyzed_segment_evidence_must_be_sent_frames_inside_the_window(self):
        from aba_demo.movement_schema import validate_movement_segment

        good = analyzed('mov-000000', 0.0, 2.0)
        self.assertEqual(validate_movement_segment(good, 10.0), good)
        bad = [
            analyzed('mov-000000', 0.0, 2.0, body_position_change_evidence_times=[0.0]),
            analyzed('mov-000000', 0.0, 2.0, body_position_change_evidence_times=[0.0, 0.7]),
            analyzed('mov-000000', 0.0, 2.0, head_turn_evidence_times=[0.0, 0.5]),
            analyzed('mov-000000', 0.0, 2.0, child_separable='ambiguous'),
            analyzed('mov-000000', 0.0, 2.0, sent_frame_times=[0.0, 0.5, 2.5]),
            analyzed('mov-000000', 0.0, 2.0, sent_image_sha256=['D' * 64] * 6),
            analyzed('mov-000000', 0.0, 2.0, max_other_overlap=1.5),
            analyzed('mov-000000', 0.0, 2.0, target_id=True),
            analyzed('mov-000000', 0.0, 12.0),
            analyzed('bad id', 0.0, 2.0),
            analyzed('mov-000000', 0.0, 2.0, clinician_confirmation='auto'),
            {**analyzed('mov-000000', 0.0, 2.0), 'notes': 'free prose'},
        ]
        for segment in bad:
            with self.subTest(segment=segment), \
                    self.assertRaisesRegex(ValueError, 'invalid_movement_segment'):
                validate_movement_segment(segment, 10.0)


class MovementDocumentTests(unittest.TestCase):
    def test_document_tiles_decoded_time_and_encodes_canonically(self):
        from aba_demo.movement_schema import (
            encode_movement_document, unread_segment, validate_movement_document)

        segments = [analyzed('mov-000000', 0.0, 2.0),
                    unread_segment('mov-000001', 2.0, 4.0, 'identity_uncertain')]
        encoded = encode_movement_document(document(segments), 10.0)
        self.assertEqual(encoded, encode_movement_document(json.loads(encoded), 10.0))
        self.assertEqual(json.loads(encoded)['segments'][0]['status'], 'analyzed')
        unread = [unread_segment('mov-000000', 0.0, 4.0, 'identity_uncertain')]
        self.assertIsNone(validate_movement_document(document(unread, prov=None), 10.0)['provenance'])

    def test_document_rejects_gaps_wrong_coverage_and_provenance_mismatch(self):
        from aba_demo.movement_schema import unread_segment, validate_movement_document

        first = analyzed('mov-000000', 0.0, 2.0)
        gap = [first, unread_segment('mov-000001', 2.5, 4.0, 'identity_uncertain')]
        late = [unread_segment('mov-000000', 0.5, 4.0, 'identity_uncertain')]
        duplicate = [first, analyzed('mov-000000', 2.0, 4.0)]
        short = [first]
        unread = [unread_segment('mov-000000', 0.0, 4.0, 'identity_uncertain')]
        config = reading_config()
        config['frames_per_window'] = 5
        cases = [
            document(gap), document(late, prov=None), document(duplicate), document(short),
            document(unread), document([first], prov=None, decoded_seconds=2.0),
            document([first], decoded_seconds=12.0),
            {**document([first], decoded_seconds=2.0), 'kind': 'context'},
            {**document([first], decoded_seconds=2.0), 'reading_config': config},
            {**document([first], decoded_seconds=2.0), 'source_sha256': 'A' * 64},
            {**document([first], decoded_seconds=2.0), 'extra': True},
            document([], decoded_seconds=2.0),
        ]
        for value in cases:
            with self.subTest(value=value), \
                    self.assertRaisesRegex(ValueError, 'invalid_movement_document'):
                validate_movement_document(value, 10.0)


if __name__ == '__main__':
    unittest.main()
