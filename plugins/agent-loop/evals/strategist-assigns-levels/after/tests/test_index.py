import json
import unittest

from textutil.index import dump_index


class IndexTest(unittest.TestCase):
    def test_url_field(self):
        (line,) = dump_index(["Hello World"]).splitlines()
        self.assertEqual(json.loads(line), {"title": "Hello World", "url": "/hello-world/"})

    def test_one_line_per_title(self):
        self.assertEqual(len(dump_index(["a", "b", "c"]).splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
