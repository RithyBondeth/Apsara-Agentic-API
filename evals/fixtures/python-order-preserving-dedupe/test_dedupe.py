import unittest

from dedupe import dedupe


class DedupeTests(unittest.TestCase):
    def test_preserves_first_seen_order(self):
        self.assertEqual(dedupe(["b", "a", "b", "c", "a"]), ["b", "a", "c"])

    def test_accepts_a_generator(self):
        self.assertEqual(dedupe(value for value in [3, 1, 3, 2]), [3, 1, 2])

    def test_empty_input(self):
        self.assertEqual(dedupe([]), [])


if __name__ == "__main__":
    unittest.main()
