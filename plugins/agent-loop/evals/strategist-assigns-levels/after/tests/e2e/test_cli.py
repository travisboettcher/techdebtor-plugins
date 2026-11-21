"""End to end: the CLI run as a process, as a user runs it."""

import subprocess
import sys
import unittest


def run_cli(stdin: str) -> str:
    done = subprocess.run([sys.executable, "-m", "textutil.cli"], input=stdin,
                          capture_output=True, text=True, check=True, timeout=30)
    return done.stdout


class CliTest(unittest.TestCase):
    def test_hello_world(self):
        self.assertIn('<a href="/hello-world/">Hello World</a>', run_cli("Hello World\n"))

    def test_accented_title(self):
        self.assertIn('href="/cafe-au-lait/"', run_cli("Café au lait\n"))


if __name__ == "__main__":
    unittest.main()
