"""Movement task over the privacy-checked adapter, and session reading with fakes."""
import json
import unittest
import unittest.mock

JPEG = b'\xff\xd8fixture\xff\xd9'


def window_frames(times=(2.5, 3.0)):
    return [{'time': time, 'identity': 'confirmed', 'scene_jpeg': JPEG,
             'target_crop_jpeg': JPEG, 'target_box': [0.1, 0.1, 0.9, 0.9]} for time in times]


def envelope(content, *, model='vendor/model:free', finish='stop'):
    return json.dumps({
        'model': model,
        'choices': [{'finish_reason': finish,
                     'message': {'role': 'assistant', 'content': content}}],
        'openrouter_metadata': {'requested': model, 'endpoints': {'available': [
            {'provider': 'fixture-provider', 'model': model, 'selected': True}]}},
    }).encode('utf-8')


def fixture_task(parse=None):
    from aba_demo.openrouter_context import VisualTask

    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {'value': {'type': 'string', 'enum': ['x']}}, 'required': ['value']}
    return VisualTask(name='fixture_task', prompt='FIXTURE PROMPT',
                      output_schema=lambda count: dict(schema, title=str(count)),
                      parse=parse or (lambda content, times: {'value': json.loads(content)['value'],
                                                              'times': times}))


class VisualTaskAdapterTests(unittest.TestCase):
    def test_task_replaces_prompt_schema_and_parser_but_keeps_privacy_flags(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter

        transport = unittest.mock.Mock(return_value=(200, envelope('{"value":"x"}')))
        result = OpenRouterContextAdapter(
            api_key='fixture-key', model='vendor/model:free', transport=transport,
            task=fixture_task(), max_tokens=8192,
        ).analyze(window_frames(), source_sha256='a' * 64)
        request = json.loads(transport.call_args.kwargs['body'])
        self.assertEqual(request['messages'][0]['content'], 'FIXTURE PROMPT')
        self.assertEqual(request['response_format']['json_schema']['name'], 'fixture_task')
        self.assertTrue(request['response_format']['json_schema']['strict'])
        self.assertEqual(request['response_format']['json_schema']['schema']['title'], '2')
        self.assertEqual(request['provider'], {'require_parameters': True,
                                               'data_collection': 'deny',
                                               'allow_fallbacks': False})
        self.assertEqual((request['temperature'], request['max_tokens']), (0, 8192))
        labels = [json.loads(part['text']) for part in request['messages'][1]['content']
                  if part['type'] == 'text']
        self.assertEqual([label['position'] for label in labels], [0, 1])
        self.assertEqual([label['time'] for label in labels], [2.5, 3.0])
        self.assertEqual(result['observation'], {'value': 'x', 'times': [2.5, 3.0]})
        self.assertEqual(result['provenance']['endpoint_provider'], 'fixture-provider')

    def test_pinned_provider_is_requested_and_verified_without_relaxing_privacy(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

        transport = unittest.mock.Mock(return_value=(200, envelope('{"value":"x"}')))
        OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                 transport=transport, task=fixture_task(),
                                 provider_order=['fixture-provider']
                                 ).analyze(window_frames(), source_sha256='a' * 64)
        request = json.loads(transport.call_args.kwargs['body'])
        self.assertEqual(request['provider'], {'require_parameters': True,
                                               'data_collection': 'deny',
                                               'allow_fallbacks': False,
                                               'order': ['fixture-provider']})
        with self.assertRaises(OpenRouterContextError) as caught:
            OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                     transport=transport, task=fixture_task(),
                                     provider_order=['Other']
                                     ).analyze(window_frames(), source_sha256='a' * 64)
        self.assertEqual(caught.exception.code, 'provider_response_invalid')
        refused = unittest.mock.Mock()
        for order in ([], ['a'] * 4, 'Wafer', [''], [7]):
            with self.subTest(order=order), self.assertRaises(OpenRouterContextError) as caught:
                OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                         transport=refused, provider_order=order
                                         ).analyze(window_frames(), source_sha256='a' * 64)
            self.assertEqual(caught.exception.code, 'invalid_config')
        refused.assert_not_called()

    def test_context_requests_keep_their_existing_shape_without_a_task(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter, SYSTEM_PROMPT

        output = {'activity_suggestion': 'unclear', 'activity_status': 'not_observable',
                  'target_material_interaction': 'not_observable',
                  'adult_target_interaction_visible': 'not_observable', 'evidence_times': []}
        transport = unittest.mock.Mock(return_value=(200, envelope(json.dumps(output))))
        OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                 transport=transport).analyze(window_frames((1.0,)),
                                                              source_sha256='a' * 64)
        request = json.loads(transport.call_args.kwargs['body'])
        self.assertEqual(request['messages'][0]['content'], SYSTEM_PROMPT)
        self.assertEqual(request['response_format']['json_schema']['name'], 'aba_visible_context')
        text = json.loads(request['messages'][1]['content'][0]['text'])
        self.assertEqual(set(text), {'time', 'target_box', 'image_order'})

    def test_invalid_task_or_window_size_fails_before_transport(self):
        from aba_demo.openrouter_context import (
            OpenRouterContextAdapter, OpenRouterContextError, VisualTask)

        transport = unittest.mock.Mock()
        schema = fixture_task().output_schema
        parse = fixture_task().parse
        for task in ('not a task', VisualTask('Bad Name', 'p', schema, parse),
                     VisualTask('ok_name', '', schema, parse),
                     VisualTask('ok_name', 'p', 'not callable', parse)):
            with self.subTest(task=task), self.assertRaises(OpenRouterContextError) as caught:
                OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                         transport=transport, task=task
                                         ).analyze(window_frames(), source_sha256='a' * 64)
            self.assertEqual(caught.exception.code, 'invalid_config')

        def refuse(count):
            raise ValueError('invalid_movement_input')

        with self.assertRaises(OpenRouterContextError) as caught:
            OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                     transport=transport,
                                     task=VisualTask('ok_name', 'p', refuse, parse)
                                     ).analyze(window_frames(), source_sha256='a' * 64)
        self.assertEqual(caught.exception.code, 'invalid_input')
        transport.assert_not_called()

    def test_parser_rule_reaches_the_error_detail_but_model_text_never_does(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

        def reject(content, times):
            raise ValueError('invalid_movement_output:needs_two_frames:head_turn')

        def leak(content, times):
            raise ValueError('secret model text ' + content)

        for parse, detail in ((reject, 'invalid_movement_output:needs_two_frames:head_turn'),
                              (leak, 'response_rejected')):
            transport = unittest.mock.Mock(return_value=(200, envelope('{"value":"x"}')))
            with self.subTest(detail=detail), self.assertRaises(OpenRouterContextError) as caught:
                OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                         transport=transport, task=fixture_task(parse)
                                         ).analyze(window_frames(), source_sha256='a' * 64)
            self.assertEqual(caught.exception.code, 'provider_response_invalid')
            self.assertEqual(caught.exception.detail, detail)

    def test_reasoning_text_can_be_excluded_without_relaxing_bounds_or_privacy(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

        transport = unittest.mock.Mock(return_value=(200, envelope('{"value":"x"}')))
        OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                 transport=transport, task=fixture_task(),
                                 reasoning={'effort': 'low', 'exclude': True}
                                 ).analyze(window_frames(), source_sha256='a' * 64)
        request = json.loads(transport.call_args.kwargs['body'])
        self.assertEqual(request['reasoning'], {'effort': 'low', 'exclude': True})
        self.assertEqual(request['provider']['data_collection'], 'deny')
        self.assertFalse(request['provider']['allow_fallbacks'])
        plain = unittest.mock.Mock(return_value=(200, envelope('{"value":"x"}')))
        OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                 transport=plain, task=fixture_task()
                                 ).analyze(window_frames(), source_sha256='a' * 64)
        self.assertNotIn('reasoning', json.loads(plain.call_args.kwargs['body']))
        refused = unittest.mock.Mock()
        for reasoning in ({'effort': 'huge'}, {'exclude': 'yes'}, {'max_tokens': 5}, 'low', {}):
            with self.subTest(reasoning=reasoning), self.assertRaises(OpenRouterContextError) as caught:
                OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                         transport=refused, task=fixture_task(),
                                         reasoning=reasoning
                                         ).analyze(window_frames(), source_sha256='a' * 64)
            self.assertEqual(caught.exception.code, 'invalid_config')
        refused.assert_not_called()

    def test_envelope_rejections_name_the_failing_part(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

        cases = [(envelope('{"value":"x"}', finish='length'), 'invalid_envelope:finish_length'),
                 (envelope('{"value":"x"}', finish='weird'), 'invalid_envelope:finish_other'),
                 (envelope('{"value":"x"}', model='other/model'), 'invalid_envelope:metadata'),
                 (b'not json', 'response_rejected')]
        for response, detail in cases:
            transport = unittest.mock.Mock(return_value=(200, response))
            with self.subTest(detail=detail), self.assertRaises(OpenRouterContextError) as caught:
                OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                         transport=transport, task=fixture_task()
                                         ).analyze(window_frames(), source_sha256='a' * 64)
            self.assertEqual(caught.exception.detail, detail)

    def test_task_parser_rejection_or_truncation_is_provider_response_invalid(self):
        from aba_demo.openrouter_context import OpenRouterContextAdapter, OpenRouterContextError

        def reject(content, times):
            raise ValueError('invalid_movement_output')

        cases = [(fixture_task(reject), envelope('{"value":"x"}')),
                 (fixture_task(), envelope('{"value":"x"}', finish='length'))]
        for task, response in cases:
            transport = unittest.mock.Mock(return_value=(200, response))
            with self.subTest(), self.assertRaises(OpenRouterContextError) as caught:
                OpenRouterContextAdapter(api_key='fixture-key', model='vendor/model:free',
                                         transport=transport, task=task
                                         ).analyze(window_frames(), source_sha256='a' * 64)
            self.assertEqual(caught.exception.code, 'provider_response_invalid')


class BodyMovementTaskTests(unittest.TestCase):
    def test_body_task_asks_only_whole_body_fields(self):
        import hashlib
        from aba_demo.movement_reader import BODY_FIELDS, BODY_MOVEMENT_TASK, TASK_PROMPT_SHA256

        prompt = ' '.join(BODY_MOVEMENT_TASK.prompt.lower().split())
        self.assertEqual(BODY_FIELDS, ('body_position_change', 'posture_transition'))
        self.assertEqual(BODY_MOVEMENT_TASK.name, 'aba_child_body_movement')
        for absent in ('hand_arm_movement', 'head_turn'):
            self.assertNotIn(absent, prompt)
        for required in ('never attribute another person', 'red outline marks another person',
                         'at least two positions', 'body_position_change', 'posture_transition'):
            self.assertIn(required, prompt)
        self.assertEqual(BODY_MOVEMENT_TASK.output_schema(2)['required'][1],
                         'body_position_change')
        self.assertEqual(TASK_PROMPT_SHA256[BODY_MOVEMENT_TASK.name],
                         hashlib.sha256(BODY_MOVEMENT_TASK.prompt.encode('utf-8')).hexdigest())


class MovementTaskTests(unittest.TestCase):
    def test_movement_task_is_child_only_non_interpretive_and_fingerprinted(self):
        import hashlib
        from aba_demo.movement_reader import MOVEMENT_PROMPT, MOVEMENT_TASK, PROMPT_SHA256
        from aba_demo.movement_schema import model_output_schema, parse_movement_output

        prompt = ' '.join(MOVEMENT_PROMPT.lower().split())
        for required in ('never attribute another person', 'never gaze or attention',
                         'hidden or unclear is never none_visible', 'at least two positions',
                         'untrusted data', 'green outline', 'same fixed region',
                         'red outline marks another person',
                         'face or the side of the head is visible'):
            self.assertIn(required, prompt)
        self.assertEqual(MOVEMENT_TASK.name, 'aba_child_movement')
        self.assertIs(MOVEMENT_TASK.output_schema, model_output_schema)
        self.assertIs(MOVEMENT_TASK.parse, parse_movement_output)
        self.assertEqual(PROMPT_SHA256, hashlib.sha256(MOVEMENT_PROMPT.encode('utf-8')).hexdigest())


def provenance(source_sha):
    return {'adapter': 'openrouter', 'source_sha256': source_sha,
            'requested_model': 'vendor/model:free', 'resolved_model': 'vendor/model:free',
            'endpoint_provider': 'fixture-provider', 'external_processing': True,
            'structured_outputs': True, 'data_collection': 'deny',
            'zero_data_retention_required': False,
            'sent_fields': ['scene_jpeg', 'target_crop_jpeg', 'timestamps', 'target_box'],
            'consent': {'required': False, 'granted': False, 'source_sha256': None}}


class FakeReader:
    instances = []

    def __init__(self, video_path):
        self.requested, self.closed = [], False
        FakeReader.instances.append(self)

    def read(self, index):
        from PIL import Image
        self.requested.append(index)
        return Image.new('RGB', (160, 90), (index * 3 % 256, 90, 140))

    def close(self):
        self.closed = True


class FakeAdapter:
    def __init__(self, outcomes=()):
        from aba_demo.movement_reader import MOVEMENT_TASK
        self.task = MOVEMENT_TASK
        self.outcomes = list(outcomes)
        self.calls = []

    def analyze(self, frames, *, source_sha256):
        from aba_demo.openrouter_context import OpenRouterContextError
        times = [frame['time'] for frame in frames]
        self.calls.append(times)
        code = self.outcomes.pop(0) if self.outcomes else None
        if code is not None:
            raise OpenRouterContextError(code)
        return {'observation': {
            'child_separable': 'yes',
            'body_position_change': 'small',
            'body_position_change_evidence_times': [times[0], times[-1]],
            'posture_transition': 'none_visible',
            'posture_transition_evidence_times': [times[0], times[1]],
            'hand_arm_movement': 'not_observable', 'hand_arm_movement_evidence_times': [],
            'head_turn': 'ambiguous', 'head_turn_evidence_times': [],
        }, 'provenance': provenance(source_sha256)}


class MovementReadingTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from movement_fixtures import candidate

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / 'authorized.mp4'
        self.video.write_bytes(b'synthetic-source-not-video')
        self.source_sha = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.candidate = self.root / 'observations.pending.json'
        self.candidate.write_text(json.dumps(candidate(self.source_sha, uncertain={23})),
                                  encoding='utf-8')
        FakeReader.instances = []

    def tearDown(self):
        self.temp.cleanup()

    def read(self, adapter, output='movement', **options):
        from aba_demo.movement_reader import read_movement
        options.setdefault('segment_ids', ['mov-000000', 'mov-000003'])
        options.setdefault('max_requests', 4)
        return read_movement(self.video, self.candidate, self.root / output, adapter,
                             frame_reader_factory=FakeReader, **options)

    def pending(self, output='movement'):
        return self.root / output / 'movement.pending.json'

    def test_selected_windows_are_read_and_every_other_span_stays_explicit(self):
        import hashlib
        from aba_demo.movement_reader import PROMPT_SHA256
        from aba_demo.movement_schema import validate_movement_document

        adapter = FakeAdapter()
        report = self.read(adapter)
        self.assertEqual(len(adapter.calls), 2)
        self.assertTrue(FakeReader.instances[0].closed)
        encoded = self.pending().read_bytes()
        self.assertEqual(report['movement_candidate_sha256'], hashlib.sha256(encoded).hexdigest())
        document = validate_movement_document(json.loads(encoded), 6.1)
        self.assertEqual([s['status'] for s in document['segments']],
                         ['analyzed', 'not_requested', 'identity_uncertain', 'analyzed',
                          'not_requested'])
        self.assertEqual(document['reading_config']['prompt_sha256'], PROMPT_SHA256)
        self.assertEqual(document['tracking_candidate_sha256'],
                         hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        first = document['segments'][0]
        self.assertEqual(first['sent_frame_times'], adapter.calls[0])
        self.assertEqual(len(first['sent_image_sha256']), 2 * len(first['sent_frame_times']))
        self.assertEqual(first['body_position_change_evidence_times'],
                         [adapter.calls[0][0], adapter.calls[0][-1]])
        self.assertTrue(all(s['clinician_confirmation'] == 'pending'
                            for s in document['segments']))
        self.assertEqual(report['status_counts'],
                         {'analyzed': 2, 'identity_uncertain': 1, 'not_requested': 2})
        self.assertEqual((report['requests_used'], report['invalid_retries']), (2, 0))

    def test_terminal_provider_failure_aborts_without_artifacts(self):
        from aba_demo.openrouter_context import OpenRouterContextError

        for code in ('provider_credit_exhausted', 'provider_no_compatible_route',
                     'provider_unauthorized', 'provider_rate_limited'):
            with self.subTest(code=code), self.assertRaises(OpenRouterContextError):
                self.read(FakeAdapter([code]), output=code)
            self.assertFalse((self.root / code).exists())

    def test_invalid_output_retries_once_within_budget_then_marks_the_window(self):
        adapter = FakeAdapter(['provider_response_invalid', None])
        report = self.read(adapter, output='a')
        self.assertEqual((report['requests_used'], report['invalid_retries']), (3, 1))
        self.assertEqual(report['status_counts']['analyzed'], 2)
        report = self.read(FakeAdapter(['provider_response_invalid', 'provider_response_invalid']),
                           output='b', max_failed_fraction=0.5)
        self.assertEqual(report['status_counts']['provider_failed'], 1)
        failed = json.loads(self.pending('b').read_text(encoding='utf-8'))['segments'][0]
        self.assertEqual((failed['status'], len(failed['sent_image_sha256'])),
                         ('provider_failed', 2 * len(failed['sent_frame_times'])))
        no_budget = FakeAdapter(['provider_response_invalid'])
        report = self.read(no_budget, output='c', max_requests=2, max_failed_fraction=0.5)
        self.assertEqual((len(no_budget.calls), report['status_counts']['provider_failed']), (2, 1))
        with self.assertRaisesRegex(ValueError, 'too_many_provider_failures') as caught:
            self.read(FakeAdapter(['provider_timeout']), output='d')
        self.assertEqual(caught.exception.failure_codes, {'provider_timeout': 1})
        self.assertEqual(caught.exception.requests_used, 2)
        self.assertFalse(self.pending('d').exists())

    def test_refuses_unsafe_or_inconsistent_requests_before_any_call(self):
        from pathlib import Path
        from aba_demo.movement_reader import read_movement

        adapter = FakeAdapter()
        other = self.root / 'other.mp4'
        other.write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'video_does_not_match_tracking_candidate'):
            read_movement(other, self.candidate, self.root / 'x', adapter,
                          segment_ids=['mov-000000'], max_requests=2,
                          frame_reader_factory=FakeReader)
        foreign = FakeAdapter()
        foreign.task = None
        repository = Path(__file__).resolve().parents[1] / 'tests' / 'movement-must-not-exist'
        cases = [
            ('invalid_adapter', dict(adapter=foreign)),
            ('invalid_segment_selection', dict(segment_ids=['mov-000002'])),
            ('invalid_segment_selection', dict(segment_ids=['mov-999999'])),
            ('invalid_segment_selection', dict(segment_ids=[])),
            ('request_budget_too_small', dict(max_requests=1)),
            ('output_inside_repository', dict(output=repository)),
        ]
        for message, options in cases:
            call_adapter = options.pop('adapter', adapter)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.read(call_adapter, **options)
        self.assertEqual(adapter.calls, [])
        self.assertFalse(repository.exists())
        self.read(adapter, output='once')
        with self.assertRaisesRegex(ValueError, 'movement_candidate_exists'):
            self.read(FakeAdapter(), output='once')

    def test_rate_limit_waits_are_bounded_and_aborts_report_requests_used(self):
        from aba_demo.openrouter_context import OpenRouterContextError

        adapter = FakeAdapter(['provider_rate_limited', None])
        report = self.read(adapter, output='a', rate_limit_wait=0.01)
        self.assertEqual((report['requests_used'], report['rate_limit_waits']), (3, 1))
        self.assertEqual(report['status_counts']['analyzed'], 2)
        limited = FakeAdapter(['provider_rate_limited'] * 4)
        with self.assertRaises(OpenRouterContextError) as caught:
            self.read(limited, output='b', rate_limit_wait=0.01, max_requests=10)
        self.assertEqual(caught.exception.code, 'provider_rate_limited')
        self.assertEqual(caught.exception.requests_used, 3)
        self.assertFalse(self.pending('b').exists())
        with self.assertRaises(OpenRouterContextError) as caught:
            self.read(FakeAdapter(['provider_rate_limited']), output='c', rate_limit_wait=0.01,
                      max_requests=2)
        self.assertEqual(caught.exception.requests_used, 1)

    def test_rate_limit_after_a_reading_stops_early_and_keeps_completed_windows(self):
        adapter = FakeAdapter([None] + ['provider_rate_limited'] * 3)
        report = self.read(adapter, rate_limit_wait=0.01, max_requests=10)
        self.assertEqual(report['stopped_early'], 'provider_rate_limited')
        self.assertEqual(report['status_counts'],
                         {'analyzed': 1, 'identity_uncertain': 1, 'not_requested': 2,
                          'provider_failed': 1})
        self.assertEqual((report['requests_used'], report['rate_limit_waits']), (4, 2))
        statuses = [s['status'] for s in json.loads(self.pending().read_text(
            encoding='utf-8'))['segments']]
        self.assertEqual(statuses, ['analyzed', 'not_requested', 'identity_uncertain',
                                    'provider_failed', 'not_requested'])
        normal = self.read(FakeAdapter(), output='normal')
        self.assertIsNone(normal['stopped_early'])

    def test_crop_mode_is_applied_and_recorded_in_the_reading_config(self):
        report = self.read(FakeAdapter(), crop_mode='window_stable_others_marked')
        document = json.loads(self.pending().read_text(encoding='utf-8'))
        self.assertEqual(document['reading_config']['crop_mode'], 'window_stable_others_marked')
        plain = self.read(FakeAdapter(), output='plain')
        plain_document = json.loads(self.pending('plain').read_text(encoding='utf-8'))
        self.assertNotEqual(document['segments'][0]['sent_image_sha256'],
                            plain_document['segments'][0]['sent_image_sha256'])
        self.assertEqual(report['status_counts']['analyzed'], 2)

    def test_body_task_reading_records_its_task_and_rejects_unasked_fields(self):
        from aba_demo.movement_reader import BODY_MOVEMENT_TASK, TASK_PROMPT_SHA256

        class BodyAdapter(FakeAdapter):
            def __init__(self, extra=None):
                super().__init__()
                self.task = BODY_MOVEMENT_TASK
                self.extra = extra or {}

            def analyze(self, frames, *, source_sha256):
                result = super().analyze(frames, source_sha256=source_sha256)
                result['observation'].update(head_turn='not_observable', **self.extra)
                return result

        self.read(BodyAdapter())
        document = json.loads(self.pending().read_text(encoding='utf-8'))
        self.assertEqual(document['reading_config']['task'], 'aba_child_body_movement')
        self.assertEqual(document['reading_config']['prompt_sha256'],
                         TASK_PROMPT_SHA256['aba_child_body_movement'])
        first = document['segments'][0]
        self.assertEqual((first['hand_arm_movement'], first['head_turn']),
                         ('not_observable', 'not_observable'))
        with self.assertRaisesRegex(ValueError, 'invalid_adapter_result'):
            self.read(BodyAdapter({'hand_arm_movement': 'visible',
                                   'hand_arm_movement_evidence_times': []}), output='bad')

    def test_images_must_match_the_reviewed_preview_hashes(self):
        adapter = FakeAdapter()
        with self.assertRaisesRegex(ValueError, 'images_changed_since_preview'):
            self.read(adapter, expected_image_sha256={'mov-000000': ['0' * 64] * 8})
        self.assertEqual(adapter.calls, [])


if __name__ == '__main__':
    unittest.main()
