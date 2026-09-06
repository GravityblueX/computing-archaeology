from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "card-sort-merge" / "card_sort_merge.py"
SPEC = importlib.util.spec_from_file_location("card_sort_merge", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - importlib contract
    raise RuntimeError(f"could not load {SCRIPT}")
CARD_SORT_MERGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CARD_SORT_MERGE
SPEC.loader.exec_module(CARD_SORT_MERGE)


class CardSortMergeTests(unittest.TestCase):
    def card(self, key: int, payload: str) -> object:
        return CARD_SORT_MERGE.Card(key, payload)

    def test_repeated_transactions_reuse_the_matching_master_card(self) -> None:
        master = [
            self.card(30, "master-30"),
            self.card(10, "master-10"),
            self.card(50, "master-50"),
        ]
        transactions = [
            self.card(30, "tx-30-b"),
            self.card(60, "tx-60"),
            self.card(10, "tx-10-b"),
            self.card(20, "tx-20"),
            self.card(30, "tx-30-a"),
            self.card(10, "tx-10-a"),
        ]

        comparisons, matches, master_only, transaction_only = (
            CARD_SORT_MERGE.merge_join(master, transactions)
        )

        self.assertEqual(
            [
                (master_card.key, transaction.payload)
                for master_card, transaction in matches
            ],
            [
                (10, "tx-10-a"),
                (10, "tx-10-b"),
                (30, "tx-30-a"),
                (30, "tx-30-b"),
            ],
        )
        self.assertEqual([card.key for card in master_only], [50])
        self.assertEqual([card.key for card in transaction_only], [20, 60])
        self.assertLessEqual(comparisons, len(master) + len(transactions))

    def test_master_keys_must_be_unique_for_both_strategies(self) -> None:
        duplicate_master = [
            self.card(10, "master-10-a"),
            self.card(10, "master-10-b"),
        ]
        transactions = [self.card(10, "tx-10")]

        for strategy in (
            CARD_SORT_MERGE.linear_lookup,
            CARD_SORT_MERGE.merge_join,
        ):
            with self.subTest(strategy=strategy.__name__):
                with self.assertRaisesRegex(ValueError, "master keys must be unique"):
                    strategy(duplicate_master, transactions)


if __name__ == "__main__":
    unittest.main()
