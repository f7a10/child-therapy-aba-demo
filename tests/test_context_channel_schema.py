"""Context channel: closed-enum VLM notes on moments the local channels marked.

The question set follows the therapist-set activity at the moment, so the model
is only asked what is meaningful there.
"""
import json
import unittest

SOURCE = 'a' * 64
TRACKING = 'b' * 64
SEGMENTS = [{'start_time': 0.0, 'end_time': 1.0, 'activity': 'table'},
            {'start_time': 1.0, 'end_time': 2.0, 'activity': 'break'}]


def observation(activity='table', **overrides):
    value = {'table': {'child_separable': 'yes', 'child_location': 'at_table',
                       'child_handling_material': 'yes'},
             'movement': {'child_separable': 'yes', 'child_location': 'walking'},
             'break': {'child_separable': 'yes', 'child_location': 'on_floor'}}[activity]
    value.update(overrides)
    return value


def moment(index=0, *, status='read', activity='table', **overrides):
    value = {'moment_id': f'ctx-{index:06d}',
             'anchors': [{'channel': 'posture', 'event_id': f'pos-{index:06d}'}],
             'start_time': 0.4, 'end_time': 0.8,
             'detected_time': 1.2, 'frame_times': [0.4, 0.6, 0.8], 'activity': activity,
             'status': status, 'failure': None if status == 'read' else 'provider_rate_limited',
             'observation': observation(activity) if status == 'read' else None}
    value.update(overrides)
    return value


def config():
    from aba_demo.context_channel_schema import PROMPT_SHA256

    return {'model': 'deepseek/deepseek-v4.1-flash', 'provider': 'Wafer',
            'prompt_sha256': dict(PROMPT_SHA256), 'max_frames_per_moment': 3}


def document(moments=None, **overrides):
    from aba_demo.context_channel_schema import context_events

    moments = [moment()] if moments is None else moments
    events = overrides.pop('events') if 'events' in overrides else context_events(moments)
    value = {'schema_version': 3, 'kind': 'context_channel_reading', 'source_sha256': SOURCE,
             'tracking_candidate_sha256': TRACKING, 'decoded_seconds': 2.0, 'config': config(),
             'activity_segments': [dict(s) for s in SEGMENTS], 'moments': moments,
             'events': events}
    value.update(overrides)
    return value


class QuestionSetTests(unittest.TestCase):
    def test_each_activity_asks_only_its_own_closed_questions(self):
        from aba_demo.context_channel_schema import CONTEXT_TASKS

        expected = {'table': {'child_separable', 'child_location', 'child_handling_material'},
                    'movement': {'child_separable', 'child_location'},
                    'break': {'child_separable', 'child_location'}}
        self.assertEqual(set(CONTEXT_TASKS), set(expected))
        for activity, task in CONTEXT_TASKS.items():
            with self.subTest(activity):
                schema = task.output_schema(3)
                self.assertEqual(set(schema['properties']), expected[activity])
                self.assertEqual(set(schema['required']), expected[activity])
                self.assertFalse(schema['additionalProperties'])
                self.assertTrue(all('enum' in f for f in schema['properties'].values()))
                missing = {'child_handling_material'} - expected[activity]
                self.assertFalse(any(name in task.prompt for name in missing))
                self.assertNotIn('adult', task.prompt)
                self.assertNotIn('activity', task.prompt.lower())
                for count in (1, 5):
                    with self.assertRaises(ValueError):
                        task.output_schema(count)

    def test_hand_contact_is_never_asked(self):
        from aba_demo.context_channel_schema import CONTEXT_TASKS, FIELD_VALUES

        self.assertNotIn('adult_hand_contact', FIELD_VALUES)
        self.assertFalse(any('hand_contact' in task.prompt for task in CONTEXT_TASKS.values()))

    def test_parser_accepts_only_the_question_set(self):
        from aba_demo.context_channel_schema import CONTEXT_TASKS

        table, rest = CONTEXT_TASKS['table'], CONTEXT_TASKS['break']
        times = [0.4, 0.6]
        self.assertEqual(table.parse(json.dumps(observation()), times), observation())
        self.assertEqual(rest.parse(json.dumps(observation('break')), times),
                         observation('break'))
        unseparable = observation(child_separable='no', child_location='not_observable',
                                  child_handling_material='not_observable')
        self.assertEqual(table.parse(json.dumps(unseparable), times), unseparable)
        cases = {
            'question_of_other_set': (rest, json.dumps(observation())),
            'dropped_question': (table, json.dumps({**observation(), 'adult_hand_contact': 'no'})),
            'extra': (table, json.dumps({**observation(), 'note': 'calm'})),
            'missing': (table, json.dumps({k: v for k, v in observation().items()
                                           if k != 'child_location'})),
            'bad_enum': (table, json.dumps(observation(child_location='kitchen'))),
            'claims_when_not_separable': (table, json.dumps(observation(child_separable='no'))),
            'not_json': (table, 'at_table'),
            'duplicate_key': (table, '{"child_separable":"yes","child_separable":"no"}'),
            'too_long': (table, ' ' * 9000),
        }
        for name, (task, raw) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, 'invalid_context'):
                task.parse(raw, times)


class ContextDocumentTests(unittest.TestCase):
    def test_read_moments_become_suggested_notes(self):
        from aba_demo.context_channel_schema import (
            encode_context_channel_document, validate_context_channel_document)

        value = document([moment(0),
                          moment(1, activity='break', start_time=1.0, end_time=1.4,
                                 detected_time=1.6, frame_times=[1.0, 1.4]),
                          moment(2, status='unread', activity='break', start_time=1.2,
                                 end_time=1.6, detected_time=1.8, frame_times=[1.2, 1.6])])
        self.assertEqual([e['event_id'] for e in value['events']], ['ctx-000000', 'ctx-000001'])
        event = value['events'][0]
        self.assertEqual((event['kind'], event['evidence_times']), ('context_note', [0.4, 0.6, 0.8]))
        self.assertEqual(event['details'], observation())
        self.assertEqual(value['events'][1]['details'], observation('break'))
        self.assertEqual(validate_context_channel_document(value, 2.5), value)
        encoded = encode_context_channel_document(value, 2.5)
        self.assertEqual(encoded, encode_context_channel_document(json.loads(encoded), 2.5))

    def test_document_is_strict_and_self_consistent(self):
        from aba_demo.context_channel_schema import validate_context_channel_document

        def edited(change):
            value = document()
            change(value)
            return value

        cases = {
            'fabricated_event': edited(lambda d: d['events'].append(
                {**d['events'][0], 'event_id': 'ctx-000009'})),
            'edited_detail': edited(lambda d: d['events'][0]['details'].update(
                child_location='on_floor')),
            'activity_not_from_segments': document([moment(activity='movement',
                                                           observation=observation('movement'))]),
            'answers_of_other_set': document([moment(observation=observation('break'))],
                                             events=[]),
            'segments_not_tiling': document(activity_segments=SEGMENTS[:1]),
            'unknown_activity': document(activity_segments=[
                {'start_time': 0.0, 'end_time': 2.0, 'activity': 'tantrum'}]),
            'unread_with_observation': document([moment(status='unread',
                                                        observation=observation())]),
            'read_without_observation': document([moment(observation=None)], events=[]),
            'bad_observation': document(
                [moment(observation=observation(child_separable='no'))], events=[]),
            'frames_outside_moment': document([moment(frame_times=[0.2, 0.6])]),
            'one_frame': document([moment(frame_times=[0.4])]),
            'shown_before_end': document([moment(detected_time=0.7)]),
            'unknown_anchor_channel': document([moment(anchors=[{'channel': 'context',
                                                                 'event_id': 'x'}])]),
            'no_anchor': document([moment(anchors=[])]),
            'duplicate_anchor': document([moment(anchors=[
                {'channel': 'posture', 'event_id': 'pos-1'}] * 2)]),
            'duplicate_ids': document([moment(0), moment(0)]),
            'bad_failure_code': document([moment(status='unread', failure='Some text!')]),
            'other_prompt': document(config={**config(), 'prompt_sha256': {
                **config()['prompt_sha256'], 'table': 'f' * 64}}),
            'old_schema': document(schema_version=2),
            'wrong_kind': document(kind='context_reading'),
            'after_session': document(decoded_seconds=3.0),
            'extra_key': document(note='x'),
        }
        for name, value in cases.items():
            with self.subTest(name), \
                    self.assertRaisesRegex(ValueError, 'invalid_context_channel_document'):
                validate_context_channel_document(value, 2.5)


class ContextChannelRegistryTests(unittest.TestCase):
    def test_context_notes_reach_the_timeline_as_suggestions(self):
        from aba_demo.channel_events import reading_for_document
        from aba_demo.session_timeline import build_timeline
        from test_posture_schema import document as posture_document

        reading = reading_for_document(document(), 2.5)
        self.assertEqual(reading['channel'], 'context')
        self.assertEqual(reading['events'][0]['origin'], 'suggested')
        self.assertEqual(reading['events'][0]['details'], observation())
        timeline = build_timeline({'posture': (posture_document(), 'c' * 64),
                                   'context': (document(), 'd' * 64)},
                                  [{'start_time': 0.0, 'end_time': 2.0, 'activity': 'table'}], 2.5)
        note = [e for e in timeline['entries'] if e['channel'] == 'context'][0]
        self.assertEqual((note['origin'], note['level']), ('suggested', 'info'))


if __name__ == '__main__':
    unittest.main()
