import unittest

from notes.store import NoteStore


class NoteStoreTest(unittest.TestCase):
    def test_add_then_get(self):
        store = NoteStore()
        self.assertEqual(store.get(store.add("hi")), "hi")

    def test_empty_note_is_rejected(self):
        with self.assertRaises(ValueError):
            NoteStore().add("  ")


if __name__ == "__main__":
    unittest.main()
