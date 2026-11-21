"""An in-memory note store."""


class NoteStore:
    def __init__(self):
        self._notes: dict[int, str] = {}
        self._next = 1

    def add(self, text: str) -> int:
        if not text.strip():
            raise ValueError("empty note")
        note_id = self._next
        self._notes[note_id] = text
        self._next += 1
        return note_id

    def get(self, note_id: int) -> str:
        return self._notes[note_id]
