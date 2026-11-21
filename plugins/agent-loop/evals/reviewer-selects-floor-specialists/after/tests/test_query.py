import unittest

from textutil.query import parse_query


class ParseQueryTest(unittest.TestCase):
    def test_pairs(self):
        self.assertEqual(parse_query("a=1&b=2"), {"a": "1", "b": "2"})

    def test_missing_equals(self):
        with self.assertRaises(ValueError):
            parse_query("a=1&b")


if __name__ == "__main__":
    unittest.main()
