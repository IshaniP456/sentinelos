"""Contract tests for the in-memory workflow document store.

Author: Tishneet
"""

import concurrent.futures
import unittest

from backend.workflows.store import Conflict, MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_missing_and_versioned_write(self):
        self.assertEqual(self.store.read("PLAN#1"), (0, None))
        self.assertEqual(self.store.write("PLAN#1", {"status": "PLANNING"}, 0), 1)
        self.assertEqual(self.store.write("PLAN#1", {"status": "VALIDATING"}, 1), 2)
        with self.assertRaises(Conflict):
            self.store.write("PLAN#1", {"status": "COMPLETED"}, 1)
        self.assertEqual(self.store.read("PLAN#1"), (2, {"status": "VALIDATING"}))

    def test_read_write_and_list_are_isolated(self):
        value = {"actions": [{"count": 3}]}
        self.store.write("PLAN#1", value, 0)
        value["actions"][0]["count"] = 99
        _, result = self.store.read("PLAN#1")
        result["actions"].clear()
        records = self.store.list("PLAN#")
        records[0][2]["actions"].clear()
        self.assertEqual(self.store.read("PLAN#1")[1], {"actions": [{"count": 3}]})

    def test_transaction_is_all_or_nothing(self):
        self.store.write("WORLD", {"inventory": 33}, 0)
        with self.assertRaises(Conflict):
            self.store.transact([("MARKER#1", {"executed": True}, 0),
                                 ("WORLD", {"inventory": 30}, 0)])
        self.assertEqual(self.store.read("MARKER#1"), (0, None))
        self.assertEqual(self.store.read("WORLD"), (1, {"inventory": 33}))
        self.store.transact([("MARKER#1", {"executed": True}, 0),
                             ("WORLD", {"inventory": 30}, 1)])
        self.assertEqual(self.store.read("WORLD"), (2, {"inventory": 30}))

    def test_transaction_validates_every_entry_before_writes(self):
        invalid = [[("A", {}, 0), ("A", {}, 0)],
                   [("A", {}, 0), ("B", {"not_json": set()}, 0)],
                   [(str(n), {}, 0) for n in range(101)]]
        for mutations in invalid:
            with self.subTest(mutations=str(mutations)[:100]):
                with self.assertRaises((TypeError, ValueError)):
                    self.store.transact(mutations)
                self.assertEqual(self.store.list(""), [])

    def test_invalid_version_document_and_nonfinite_values(self):
        for version in (True, -1, 1.5, "0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.store.write("PLAN#1", {}, version)
        for value in (None, [], {"number": float("nan")}, {"number": float("inf")}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.write("PLAN#1", value, 0)

    def test_prefix_filter_and_empty_transaction(self):
        self.store.transact([])
        self.store.write("WORLD", {}, 0)
        self.store.write("PLAN#2", {}, 0)
        self.store.write("PLAN#1", {}, 0)
        self.assertEqual([entry[0] for entry in self.store.list("PLAN#")], ["PLAN#1", "PLAN#2"])

    def test_concurrent_compare_and_swap_loses_no_updates(self):
        self.store.write("COUNTER", {"count": 0}, 0)

        def increment(_):
            while True:
                version, value = self.store.read("COUNTER")
                value["count"] += 1
                try:
                    self.store.write("COUNTER", value, version)
                    return
                except Conflict:
                    continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(increment, range(200)))
        self.assertEqual(self.store.read("COUNTER"), (201, {"count": 200}))


if __name__ == "__main__":
    unittest.main()
