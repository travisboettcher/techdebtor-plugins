import unittest

from textutil.links import render_links


class LinksTest(unittest.TestCase):
    def test_links_to_url(self):
        line = '{"title": "Hello", "url": "/hello/"}'
        self.assertEqual(render_links(line), ['<a href="/hello/">Hello</a>'])

    def test_escapes_title(self):
        line = '{"title": "a < b", "url": "/a-b/"}'
        self.assertEqual(render_links(line), ['<a href="/a-b/">a &lt; b</a>'])


if __name__ == "__main__":
    unittest.main()
