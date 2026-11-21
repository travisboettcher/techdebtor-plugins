import unittest

from textutil import slugify


class SlugifyTest(unittest.TestCase):
    def test_words_are_joined_by_hyphens(self):
        self.assertEqual(slugify("Hello, World"), "hello-world")

    def test_accents_are_dropped(self):
        self.assertEqual(slugify("Café au lait"), "cafe-au-lait")

    def test_empty_input(self):
        self.assertEqual(slugify("  !! "), "")


if __name__ == "__main__":
    unittest.main()
