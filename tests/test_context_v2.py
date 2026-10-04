"""Context v2 pilot: before/after frame planning, strict answers, local second opinion."""
import json
import unittest

from movement_fixtures import candidate


def moment_frames(data, start_index, end_index):
    time_of = {row['frame_index']: row['time'] for row in data['provenance']['causal_audit']}
    return [{'frame_index': index, 'time': time_of[index]} for index in (start_index, end_index)]


class PlanTests(unittest.TestCase):
    def test_before_and_after_frames_stay_on_the_same_unbroken_binding(self):
        from aba_demo.context_v2 import plan_v2_frames

        data = candidate('a' * 64, decoded=120)  # 10 fps, a sample every 0.5 s
        roles, frames = plan_v2_frames(data, moment_frames(data, 50, 60))
        self.assertEqual(roles, ['before', 'start', 'end', 'after'])
        self.assertEqual([f['time'] for f in frames], [2.0, 5.0, 6.0, 9.0])  # 3 s outside
        self.assertTrue(all(f['other_boxes'] for f in frames))
        # An identity gap between the moment and the BEFORE side drops that frame.
        broken = candidate('a' * 64, decoded=120, uncertain={42})
        roles, frames = plan_v2_frames(broken, moment_frames(broken, 50, 60))
        self.assertEqual(roles, ['start', 'end', 'after'])
        switched = candidate('a' * 64, decoded=120, switch_at=55)
        with self.assertRaisesRegex(ValueError, 'moment_crosses_identity_gap'):
            plan_v2_frames(switched, moment_frames(switched, 50, 60))

    def test_a_child_cut_by_the_frame_edge_is_not_used_before_or_after(self):
        from aba_demo.context_v2 import plan_v2_frames

        data = candidate('a' * 64, decoded=120, target_box=[0.6, 0.2, 1.0, 0.9])
        roles, _ = plan_v2_frames(data, moment_frames(data, 50, 60))
        self.assertEqual(roles, ['start', 'end'])


class AnswerTests(unittest.TestCase):
    def answer(self, **changes):
        value = {'child_separable': 'yes', 'child_location': 'at_table',
                 'child_position_after': 'standing', 'adult_proximity': 'close',
                 'task_materials_near_child': 'present', 'adult_movement_before': 'stayed',
                 'materials_change_before': 'no_change', 'adult_movement_after': 'moved_away',
                 'materials_change_after': 'no_change'}
        value.update(changes)
        return json.dumps({k: v for k, v in value.items() if v is not None})

    def test_only_the_questions_of_the_layout_are_accepted(self):
        from aba_demo.context_v2 import ROLES, task_for

        full, short = task_for(ROLES), task_for(('start', 'end'))
        self.assertEqual(full.parse(self.answer(), [1, 2, 3, 4])['adult_movement_after'],
                         'moved_away')
        self.assertIn('AFTER frame only', full.prompt)
        self.assertIn('MOMENT END frame only', short.prompt)
        self.assertEqual(sorted(short.output_schema(2)['required']),
                         ['adult_proximity', 'child_location', 'child_position_after',
                          'child_separable', 'task_materials_near_child'])
        for bad, rule in ((self.answer(adult_movement_after='guided'), 'enum'),
                          (self.answer(materials_change_after=None), 'fields'),
                          (self.answer(child_separable='no'), 'separable'),
                          ('{"a": 1, "a": 2}', 'duplicate_key'), ('{not json', 'json')):
            with self.assertRaisesRegex(ValueError, 'invalid_context:' + rule):
                full.parse(bad, [1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, 'invalid_context_window'):
            full.output_schema(3)
        with self.assertRaisesRegex(ValueError, 'invalid_context_layout'):
            task_for(('before', 'end'))

    def test_no_clinical_or_intent_wording_is_asked(self):
        from aba_demo.context_v2 import LAYOUTS, prompt_for

        for roles in LAYOUTS:
            prompt = prompt_for(roles).lower()
            for word in ('reinforc', 'escape', 'tantrum', 'happy', 'angry', 'attention-seeking'):
                self.assertNotIn(word, prompt)


class SecondOpinionTests(unittest.TestCase):
    def test_the_model_view_after_the_change_is_compared_locally(self):
        from aba_demo.context_v2 import second_opinion

        stood = [('posture', 'sit_to_stand')]
        self.assertEqual(second_opinion(stood, {'child_position_after': 'standing'}), 'agrees')
        self.assertEqual(second_opinion(stood, {'child_position_after': 'seated'}), 'disagrees')
        self.assertEqual(second_opinion(stood, {'child_position_after': 'not_observable'}),
                         'unclear')
        both = [('movement', 'large_movement'), ('posture', 'sit_to_stand')]
        self.assertEqual(second_opinion(both, {'child_position_after': 'walking'}), 'agrees')
        self.assertEqual(second_opinion([('orientation', 'turned_away_from_task')],
                                        {'child_position_after': 'seated'}), 'unclear')
        self.assertEqual(second_opinion(stood, None), 'unclear')


if __name__ == '__main__':
    unittest.main()
