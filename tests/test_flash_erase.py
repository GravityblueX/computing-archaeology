from __future__ import annotations

import runpy
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "flash-erase" / "flash_erase.py"
FLASH = runpy.run_path(SCRIPT)
FlashPage = FLASH["FlashPage"]
reclaim_block = FLASH["reclaim_block"]


def fixture(block_pages: int, live_mask: int, victim_block: int = 0):
    pages = [None] * (3 * block_pages)
    latest = {}
    replacement_block = 1 if victim_block == 0 else 0
    for offset in range(block_pages):
        logical_id = f"L{offset}"
        position = victim_block * block_pages + offset
        pages[position] = FlashPage(logical_id, f"original-{offset}")
        latest[logical_id] = position
        if not (live_mask & (1 << offset)):
            replacement = replacement_block * block_pages + offset
            pages[replacement] = FlashPage(logical_id, f"updated-{offset}")
            latest[logical_id] = replacement
    return pages, latest, list(range(2 * block_pages, 3 * block_pages))


def visible(pages, latest):
    return {
        logical_id: pages[position].value for logical_id, position in latest.items()
    }


class FlashEraseCompatibilityTests(unittest.TestCase):
    def test_original_single_hotspot_counts(self) -> None:
        self.assertEqual(FLASH["naive_updates"](), [128, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(FLASH["log_structured_updates"](), ([1] * 8, 128))
        for updates, expected_erases in (
            (0, 0),
            (1, 0),
            (63, 0),
            (64, 0),
            (65, 1),
            (128, 8),
        ):
            with self.subTest(updates=updates):
                erases, writes = FLASH["log_structured_updates"](updates)
                self.assertEqual(sum(erases), expected_erases)
                self.assertEqual(writes, updates)

    def test_default_command_retains_original_output(self) -> None:
        output = subprocess.check_output([sys.executable, "-B", str(SCRIPT)], text=True)
        self.assertEqual(
            output.splitlines()[:4],
            [
                "geometry=8_blocks x 8_pages updates=128",
                "strategy=in_place       erases=128 max_block_erases=128 spread=128",
                "strategy=append_reclaim erases= 8 max_block_erases= 1 spread= 0 physical_writes=128",
                "Counts are synthetic. The model exposes erase-before-reuse and wear placement, not NAND firmware.",
            ],
        )

    def test_default_command_exposes_live_copy_cost_and_preserved_values(self) -> None:
        output = subprocess.check_output([sys.executable, "-B", str(SCRIPT)], text=True)
        self.assertIn(
            "scenario=all_stale block_pages=8 live=0 gc_reads=0 copy_programs=0 erases=1 free_pages=8->16 net_free_gain=8",
            output,
        )
        self.assertIn(
            "scenario=mixed_live block_pages=8 live=6 gc_reads=6 copy_programs=6 erases=1 free_pages=14->16 net_free_gain=2",
            output,
        )
        self.assertIn("READ p2 L2=original", output)
        self.assertIn("PROGRAM p8 L2=original", output)
        self.assertIn("REMAP L2 p2->p8", output)
        self.assertIn("ERASE block=0 pages=p0..p3", output)
        self.assertIn(
            "values before: L0=updated L1=updated L2=original L3=original", output
        )
        self.assertIn(
            "values after:  L0=updated L1=updated L2=original L3=original", output
        )


class FlashRelocationTests(unittest.TestCase):
    def assert_trace_replays(self, pages, latest, result, block_pages, victim_block=0):
        """Independent event interpreter: every prefix must retain logical values."""
        cells, current = list(pages), dict(latest)
        victim = set(
            range(victim_block * block_pages, (victim_block + 1) * block_pages)
        )
        live = victim.intersection(current.values())
        before_values = visible(cells, current)
        self.assertEqual(
            [op.action for op in result.operations],
            ["read", "program", "remap"] * len(live) + ["erase"],
        )
        saved = None
        for op in result.operations:
            if op.action == "read":
                self.assertIn(op.source, live)
                self.assertEqual(current[op.logical_id], op.source)
                saved = cells[op.source]
                self.assertEqual(
                    (saved.logical_id, saved.value), (op.logical_id, op.value)
                )
            elif op.action == "program":
                self.assertNotIn(op.destination, victim)
                self.assertIsNone(cells[op.destination])
                self.assertIsNone(pages[op.destination])
                self.assertEqual(
                    (op.logical_id, op.value), (saved.logical_id, saved.value)
                )
                cells[op.destination] = FlashPage(op.logical_id, op.value)
            elif op.action == "remap":
                self.assertEqual(current[op.logical_id], op.source)
                self.assertEqual(cells[op.destination], saved)
                current[op.logical_id] = op.destination
                saved = None
            else:
                self.assertEqual(op.action, "erase")
                self.assertEqual(op.block, victim_block)
                self.assertFalse(victim.intersection(current.values()))
                for position in victim:
                    cells[position] = None
            self.assertEqual(visible(cells, current), before_values)
        self.assertEqual(tuple(cells), result.pages)
        self.assertEqual(current, dict(result.latest))
        self.assertEqual(cells.count(None), result.free_after)

    def test_four_page_identity_witness(self) -> None:
        pages, latest, destinations = fixture(4, 0b1100)
        result = reclaim_block(
            pages,
            latest,
            victim_block=0,
            destination_pages=destinations,
            pages_per_block=4,
        )
        self.assertEqual(dict(result.latest), {"L0": 4, "L1": 5, "L2": 8, "L3": 9})
        self.assertEqual(result.pages[8], FlashPage("L2", "original-2"))
        self.assertEqual(result.pages[9], FlashPage("L3", "original-3"))
        self.assertEqual(
            (result.gc_reads, result.copy_programs, result.erases), (2, 2, 1)
        )
        self.assertEqual(
            (result.free_before, result.free_after, result.net_free_gain), (6, 8, 2)
        )
        self.assert_trace_replays(pages, latest, result, 4)

    def test_272_live_masks_match_independent_page_set_oracle(self) -> None:
        cases = 0
        for block_pages in (4, 8):
            for mask in range(1 << block_pages):
                with self.subTest(block_pages=block_pages, live_mask=mask):
                    pages, latest, destinations = fixture(block_pages, mask)
                    victim = set(range(block_pages))
                    live_positions = victim.intersection(latest.values())
                    translation = dict(zip(sorted(live_positions), destinations))
                    expected_map = {
                        key: translation.get(position, position)
                        for key, position in latest.items()
                    }
                    # Construct the full expected image directly, without a GC loop.
                    expected_image = dict(enumerate(pages))
                    expected_image.update(dict.fromkeys(victim))
                    expected_image.update(
                        {
                            translation[position]: pages[position]
                            for position in live_positions
                        }
                    )
                    result = reclaim_block(
                        pages,
                        latest,
                        victim_block=0,
                        destination_pages=destinations,
                        pages_per_block=block_pages,
                    )
                    self.assertEqual(dict(result.latest), expected_map)
                    self.assertEqual(dict(enumerate(result.pages)), expected_image)
                    self.assertEqual(
                        visible(result.pages, result.latest), visible(pages, latest)
                    )
                    self.assertEqual(result.gc_reads, len(live_positions))
                    self.assertEqual(result.copy_programs, len(live_positions))
                    self.assertEqual(result.erases, 1)
                    self.assertEqual(
                        result.net_free_gain, block_pages - len(live_positions)
                    )
                    self.assertEqual(result.free_before, pages.count(None))
                    self.assertEqual(result.free_after, result.pages.count(None))
                    self.assert_trace_replays(pages, latest, result, block_pages)
                    cases += 1
        self.assertEqual(cases, 272)

    def test_all_stale_needs_no_destinations_or_copies(self) -> None:
        pages, latest, _ = fixture(8, 0)
        result = reclaim_block(pages, latest, victim_block=0, destination_pages=[])
        self.assertEqual([op.action for op in result.operations], ["erase"])
        self.assertEqual(result.net_free_gain, 8)
        self.assertEqual(dict(result.latest), latest)

    def test_forced_all_live_relocation_yields_no_net_capacity(self) -> None:
        pages, latest, destinations = fixture(8, 255)
        result = reclaim_block(
            pages, latest, victim_block=0, destination_pages=destinations
        )
        self.assertEqual(
            (result.gc_reads, result.copy_programs, result.erases), (8, 8, 1)
        )
        self.assertEqual(
            (result.free_before, result.free_after, result.net_free_gain), (16, 16, 0)
        )
        self.assert_trace_replays(pages, latest, result, 8)

    def test_duplicate_old_versions_do_not_become_live(self) -> None:
        pages = [
            FlashPage("A", "oldest"),
            FlashPage("A", "older"),
            FlashPage("A", "current"),
            FlashPage("B", "kept"),
            None,
            None,
            None,
            None,
        ]
        latest = {"A": 2, "B": 3}
        result = reclaim_block(
            pages,
            latest,
            victim_block=0,
            destination_pages=[4, 5, 6, 7],
            pages_per_block=4,
        )
        self.assertEqual(
            visible(result.pages, result.latest), {"A": "current", "B": "kept"}
        )
        self.assertEqual(
            [op.source for op in result.operations if op.action == "read"], [2, 3]
        )
        self.assertEqual(result.copy_programs, 2)
        self.assert_trace_replays(pages, latest, result, 4)

    def test_nonzero_victim_and_supplied_destination_order(self) -> None:
        pages, latest, destinations = fixture(4, 0b1010, victim_block=1)
        destinations.reverse()
        result = reclaim_block(
            pages,
            latest,
            victim_block=1,
            destination_pages=destinations,
            pages_per_block=4,
        )
        self.assertEqual(dict(result.latest), {"L0": 0, "L1": 11, "L2": 2, "L3": 10})
        self.assertEqual(result.pages[4:8], (None,) * 4)
        self.assertEqual(result.pages[:4], tuple(pages[:4]))
        self.assertIsNone(result.pages[8])  # Extra supplied destinations remain unused.
        self.assertIsNone(result.pages[9])
        self.assert_trace_replays(pages, latest, result, 4, victim_block=1)

    def test_input_and_result_states_are_isolated(self) -> None:
        pages, latest, destinations = fixture(4, 0b1100)
        before_pages, before_latest, before_destinations = (
            list(pages),
            dict(latest),
            list(destinations),
        )
        first = reclaim_block(
            pages,
            latest,
            victim_block=0,
            destination_pages=destinations,
            pages_per_block=4,
        )
        other_pages, other_latest, other_destinations = fixture(8, 0)
        reclaim_block(
            other_pages,
            other_latest,
            victim_block=0,
            destination_pages=other_destinations,
        )
        second = reclaim_block(
            tuple(pages),
            latest,
            victim_block=0,
            destination_pages=tuple(destinations),
            pages_per_block=4,
        )
        self.assertEqual(first, second)
        self.assertEqual(
            (pages, latest, destinations),
            (before_pages, before_latest, before_destinations),
        )
        pages[4] = None
        latest["L0"] = 0
        destinations.clear()
        self.assertEqual(first.pages[4], FlashPage("L0", "updated-0"))
        self.assertEqual(first.latest["L0"], 4)
        with self.assertRaises(TypeError):
            first.latest["L0"] = 0

    def test_unsafe_destination_plans_leave_input_state_unchanged(self) -> None:
        for destinations in ([8], [8, 8], [0, 8], [4, 8], [8, 12]):
            with self.subTest(destinations=destinations):
                pages, latest, _ = fixture(4, 0b1100)
                before = list(pages), dict(latest)
                with self.assertRaises(ValueError):
                    reclaim_block(
                        pages,
                        latest,
                        victim_block=0,
                        destination_pages=destinations,
                        pages_per_block=4,
                    )
                self.assertEqual((pages, latest), before)

    def test_latest_map_must_resolve_to_its_actual_logical_page(self) -> None:
        for bad_position in (0, 1, 6, 12):
            pages, latest, destinations = fixture(4, 0b1100)
            # L2 must not point to a different logical ID, erased or absent page.
            latest["L2"] = bad_position
            with self.subTest(position=bad_position), self.assertRaises(ValueError):
                reclaim_block(
                    pages,
                    latest,
                    victim_block=0,
                    destination_pages=destinations,
                    pages_per_block=4,
                )


if __name__ == "__main__":
    unittest.main()
