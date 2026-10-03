"""Unified channel event: the one shape every observation channel hands to the timeline."""
import copy
import unittest

from test_posture_schema import SOURCE, TRACKING, document as posture_document


def event(**overrides):
    value = {'event_id': 'pos-000000', 'channel': 'posture', 'kind': 'stand_to_sit',
             'origin': 'measured', 'start_time': 0.4, 'end_time': 0.8,
             'detected_time': 1.2, 'evidence_times': [0.4, 0.8],
             'clinician_confirmation': 'pending', 'details': {}}
    value.update(overrides)
    return value


class ChannelEventTests(unittest.TestCase):
    def test_valid_events_pass_and_are_copied(self):
        from aba_demo.channel_events import validate_channel_events

        events = [event(), event(event_id='pos-000001', kind='sit_to_stand', start_time=1.0,
                                 end_time=1.4, detected_time=1.8, evidence_times=[1.0, 1.4])]
        validated = validate_channel_events(events, 2.0)
        self.assertEqual(validated, events)
        validated[0]['evidence_times'].append(9)
        self.assertEqual(events[0]['evidence_times'], [0.4, 0.8])

    def test_each_field_is_strict(self):
        from aba_demo.channel_events import validate_channel_events

        cases = {
            'extra_key': event(note='x'),
            'missing_key': {k: v for k, v in event().items() if k != 'origin'},
            'unknown_channel': event(channel='emotion'),
            'kind_of_other_channel': event(kind='large_movement'),
            'unknown_kind': event(kind='distracted'),
            'posture_is_never_suggested': event(origin='suggested'),
            'start_after_end': event(start_time=0.9),
            'negative_start': event(start_time=-0.1, evidence_times=[-0.1, 0.8]),
            'end_after_session': event(end_time=2.5, detected_time=2.5,
                                       evidence_times=[0.4, 2.5]),
            'shown_before_it_ended': event(detected_time=0.7),
            'detected_after_session': event(detected_time=2.1),
            'no_evidence': event(evidence_times=[]),
            'evidence_outside_event': event(evidence_times=[0.4, 0.9]),
            'evidence_unordered': event(evidence_times=[0.8, 0.4]),
            'too_much_evidence': event(evidence_times=[0.4] * 9),
            'bool_time': event(start_time=True),
            'nan_time': event(end_time=float('nan')),
            'empty_id': event(event_id=''),
            'unknown_confirmation': event(clinician_confirmation='auto'),
            'details_not_object': event(details=[]),
            'details_free_text': event(details={'note': 'The child seems upset'}),
            'details_bad_key': event(details={'Bad Key': 'yes'}),
            'measured_with_details': event(details={'child_location': 'at_table'}),
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, 'invalid_channel_events'):
                validate_channel_events([value], 2.0)

    def test_list_must_be_ordered_with_unique_ids(self):
        from aba_demo.channel_events import validate_channel_events

        later = event(event_id='pos-000001', start_time=1.0, end_time=1.4, detected_time=1.8,
                      evidence_times=[1.0, 1.4])
        for events in ([event(), event()], [later, event()], 'x', [None]):
            with self.subTest(events=events), \
                    self.assertRaisesRegex(ValueError, 'invalid_channel_events'):
                validate_channel_events(events, 2.0)
        self.assertEqual(validate_channel_events([], 2.0), [])


class PostureAdapterTests(unittest.TestCase):
    def test_posture_reading_becomes_measured_channel_events(self):
        from aba_demo.channel_events import channel_reading

        reading = channel_reading('posture', posture_document(), 2.5)
        self.assertEqual(reading['source_sha256'], SOURCE)
        self.assertEqual(reading['tracking_candidate_sha256'], TRACKING)
        self.assertEqual(reading['decoded_seconds'], 2.0)
        self.assertEqual(reading['events'], [event()])

    def test_adapter_keeps_the_channel_own_strict_validation(self):
        from aba_demo.channel_events import channel_reading

        fabricated = posture_document()
        fabricated['events'][0]['detected_time'] = 0.8
        with self.assertRaisesRegex(ValueError, 'invalid_posture_document'):
            channel_reading('posture', fabricated, 2.5)
        with self.assertRaisesRegex(ValueError, 'unknown_channel'):
            channel_reading('emotion', posture_document(), 2.5)

    def test_adapter_does_not_alias_the_source_document(self):
        from aba_demo.channel_events import channel_reading

        source = posture_document()
        before = copy.deepcopy(source)
        channel_reading('posture', source, 2.5)['events'][0]['evidence_times'].append(1)
        self.assertEqual(source, before)



class OrientationAdapterTests(unittest.TestCase):
    def test_orientation_reading_becomes_measured_channel_events(self):
        from aba_demo.channel_events import channel_reading
        from test_orientation_schema import document as orientation_document

        reading = channel_reading('orientation', orientation_document(), 2.5)
        self.assertEqual(reading['events'], [event(
            event_id='ori-000000', channel='orientation', kind='turned_away_from_task')])
        fabricated = orientation_document()
        fabricated['events'][0]['detected_time'] = 0.8
        with self.assertRaisesRegex(ValueError, 'invalid_orientation_document'):
            channel_reading('orientation', fabricated, 2.5)


class LargeMovementAdapterTests(unittest.TestCase):
    def test_large_movement_reading_becomes_measured_channel_events(self):
        from aba_demo.channel_events import channel_reading
        from test_large_movement_schema import document as movement_document

        reading = channel_reading('movement', movement_document(), 2.5)
        self.assertEqual(reading['events'], [event(
            event_id='lmv-000000', channel='movement', kind='large_movement', start_time=0.2,
            end_time=0.6, detected_time=1.6, evidence_times=[0.2, 0.4, 0.6])])
        fabricated = movement_document()
        fabricated['events'][0]['detected_time'] = 0.6
        with self.assertRaisesRegex(ValueError, 'invalid_large_movement_document'):
            channel_reading('movement', fabricated, 2.5)


class DocumentKindTests(unittest.TestCase):
    def test_channel_is_found_from_the_document_kind(self):
        from aba_demo.channel_events import reading_for_document
        from test_large_movement_schema import document as movement_document
        from test_orientation_schema import document as orientation_document

        for document, channel in ((posture_document(), 'posture'),
                                  (orientation_document(), 'orientation'),
                                  (movement_document(), 'movement')):
            with self.subTest(channel=channel):
                reading = reading_for_document(document, 2.5)
                self.assertEqual(reading['channel'], channel)
                self.assertTrue(all(e['channel'] == channel for e in reading['events']))
        for value in ({**posture_document(), 'kind': 'emotion_reading'}, [], None):
            with self.subTest(value=str(value)[:20]),                     self.assertRaisesRegex(ValueError, 'unknown_channel'):
                reading_for_document(value, 2.5)

if __name__ == '__main__':
    unittest.main()
