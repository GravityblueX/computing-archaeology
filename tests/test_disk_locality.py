from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "disk-locality" / "disk_locality.py"
SPEC = importlib.util.spec_from_file_location("disk_locality", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - importlib contract
    raise RuntimeError(f"could not load {SCRIPT}")
DISK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DISK
SPEC.loader.exec_module(DISK)


class DiskLocalityTests(unittest.TestCase):
    def test_hand_calculated_workload_totals(self) -> None:
        cases = [
            ([], 0.0),
            ([0], 0.15),
            ([0, 0], 50.15),
            ([0, 1], 2.65),
            ([19, 0], 50.15),
            ([0, 20], 50.15),
            ([20], 50.15),
            ([0, 10, 0], 50.15),
            ([400], 50.15),
        ]
        for records, expected in cases:
            with self.subTest(records=records):
                self.assertAlmostEqual(DISK.run_workload(records), expected)

    def test_repeated_read_waits_after_the_first_transfer(self) -> None:
        first, second = DISK.iter_accesses([0, 0])
        self.assertEqual(first.rotation_ms, 0.0)
        self.assertEqual(first.transfer_ms, 0.15)
        self.assertEqual(first.elapsed_ms, 0.15)
        self.assertEqual(second.seek_ms, 0.0)
        self.assertAlmostEqual(second.rotation_ms, 49.85)
        self.assertAlmostEqual(second.elapsed_ms, 50.15)

    def test_rotation_continues_during_initial_and_later_seek(self) -> None:
        initial = list(DISK.iter_accesses([20]))[0]
        self.assertEqual(initial.seek_ms, 2.5)
        self.assertAlmostEqual(initial.rotation_ms, 47.5)
        later = list(DISK.iter_accesses([0, 20]))[1]
        self.assertEqual(later.seek_ms, 2.5)
        self.assertAlmostEqual(later.rotation_ms, 47.35)

    def test_exact_record_arrival_does_not_add_a_revolution(self) -> None:
        for record, expected in [(399, 47.65), (400, 50.15)]:
            with self.subTest(record=record):
                access = list(DISK.iter_accesses([record]))[0]
                self.assertEqual(access.rotation_ms, 0.0)
                self.assertAlmostEqual(access.elapsed_ms, expected)

    def test_components_account_for_each_access_and_the_workload(self) -> None:
        records = [0, 20, 19, 3999, 10, 0]
        trace = list(DISK.iter_accesses(records))
        previous = 0.0
        components = []
        self.assertEqual([access.record for access in trace], records)
        for access in trace:
            self.assertGreaterEqual(access.seek_ms, 0.0)
            self.assertGreaterEqual(access.rotation_ms, 0.0)
            self.assertLess(access.rotation_ms, DISK.FULL_ROTATION_MS)
            self.assertEqual(access.transfer_ms, DISK.TRANSFER_PER_RECORD_MS)
            cost = math.fsum([access.seek_ms, access.rotation_ms, access.transfer_ms])
            self.assertAlmostEqual(access.elapsed_ms, previous + cost)
            components.append(cost)
            previous = access.elapsed_ms
        self.assertAlmostEqual(DISK.run_workload(records), math.fsum(components))
        self.assertEqual(list(DISK.iter_accesses([])), [])

    def test_workloads_preserve_input_order_and_restart_their_clock(self) -> None:
        records = [20, 0, 20, 1]
        before = records[:]
        first = list(DISK.iter_accesses(records))
        second = list(DISK.iter_accesses(records))
        self.assertEqual(records, before)
        self.assertEqual([access.record for access in first], before)
        self.assertEqual(first, second)
        self.assertEqual(DISK.run_workload(iter(records)), first[-1].elapsed_ms)

    def test_repeated_read_clock_does_not_drift_between_revolutions(self) -> None:
        trace = list(DISK.iter_accesses([0] * 500))
        for index, access in enumerate(trace):
            self.assertAlmostEqual(access.elapsed_ms, index * 50.0 + 0.15)
            self.assertAlmostEqual(access.rotation_ms, 49.85 if index else 0.0)

    def test_documented_cli_exposes_components_and_repeated_read(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        for label in ["random-order", "same records, clustered", "sequential run"]:
            self.assertIn(label, completed.stdout)
        for component in ["seek", "rotation", "transfer", "total"]:
            self.assertIn(component, completed.stdout)
        for total in ["14375.15", "2525.15", "497.65"]:
            self.assertIn(total, completed.stdout)
        self.assertIn("Repeated record, no cache: [0, 0]", completed.stdout)
        self.assertIn("49.85", completed.stdout)
        self.assertIn("50.15", completed.stdout)
        self.assertIn("invented teaching parameters", completed.stdout)
        self.assertIn("not IBM 350 timing", completed.stdout)


if __name__ == "__main__":
    unittest.main()
