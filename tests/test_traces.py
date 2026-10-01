import unittest

import export_traces


class TestTraces(unittest.TestCase):
    def test_web_traces_are_current(self):
        self.assertEqual(export_traces.OUT.read_text(), export_traces.build(),
                         "docs/traces.js is stale; run: python export_traces.py")


if __name__ == "__main__":
    unittest.main()
