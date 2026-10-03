"""Grouping events that happen together into one reviewable moment."""
import unittest


def item(name, start, end):
    return {'name': name, 'start_time': start, 'end_time': end}


class GroupingTests(unittest.TestCase):
    def test_events_within_the_gap_form_one_moment(self):
        from aba_demo.grouping import GROUP_GAP_SECONDS, group_by_time

        self.assertEqual(GROUP_GAP_SECONDS, 1.0)
        items = [item('stood', 148.2, 148.6), item('moved', 148.0, 151.4),
                 item('sat', 31.4, 31.6), item('note', 31.4, 31.6),
                 item('later', 152.3, 152.7), item('far', 154.0, 154.2)]
        groups = group_by_time(items, key='name')
        self.assertEqual([[i['name'] for i in g] for g in groups],
                         [['note', 'sat'], ['moved', 'stood', 'later'], ['far']])

    def test_order_is_deterministic_and_input_is_not_changed(self):
        from aba_demo.grouping import group_by_time

        items = [item('b', 1.0, 1.2), item('a', 1.0, 1.2)]
        self.assertEqual([[i['name'] for i in g] for g in group_by_time(items, key='name')],
                         [['a', 'b']])
        self.assertEqual([i['name'] for i in items], ['b', 'a'])
        self.assertEqual(group_by_time([]), [])
        with self.assertRaisesRegex(ValueError, 'invalid_group_gap'):
            group_by_time(items, gap=-1)


if __name__ == '__main__':
    unittest.main()
