from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "core-memory" / "core_memory.py"
SPEC = importlib.util.spec_from_file_location("core_memory", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT}")
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


class CoreReadTraceTests(unittest.TestCase):
    def plane(self, bit=1, row=1, col=2, size=4):
        plane = CORE.CorePlane(size)
        plane.seed_checkerboard()
        plane.write(row, col, bit)
        return plane

    def test_legacy_positional_read_and_result_constructor_still_work(self):
        plane = self.plane()
        result = plane.destructive_read(1, 2, True)
        self.assertEqual(result, CORE.ReadResult(1, 2, 1, True, True))
        self.assertEqual(plane.bits[1][2], 1)

    def test_no_trace_is_empty_and_does_not_allocate_step_snapshots(self):
        plane = self.plane()
        with patch.object(CORE, "ReadStep", side_effect=AssertionError("snapshot")):
            result = plane.destructive_read(1, 2)
        self.assertEqual(result.trace, ())

    def test_restore_one_exposes_cleared_core_with_retained_logical_one(self):
        result = self.plane().destructive_read(1, 2, trace=True)
        self.assertEqual(
            [step.phase for step in result.trace],
            ["SELECT", "READ_CLEAR", "RESTORE_WRITE", "COMPLETE"],
        )
        self.assertEqual([step.core_bit for step in result.trace], [1, 0, 1, 1])
        self.assertEqual([step.observed_bit for step in result.trace], [None, 1, 1, 1])
        self.assertEqual([step.sense_pulse for step in result.trace], [None, True, True, True])
        self.assertEqual(result.trace[2].restore_action, "write-one")
        self.assertTrue(result.restored)

    def test_disabled_restore_keeps_one_cleared_and_next_read_sees_zero(self):
        plane = self.plane()
        result = plane.destructive_read(1, 2, False, trace=True)
        self.assertEqual([step.core_bit for step in result.trace], [1, 0, 0, 0])
        self.assertEqual(result.trace[2].phase, "RESTORE_SKIP")
        self.assertEqual(result.trace[2].restore_action, "disabled")
        self.assertEqual(result.observed_bit, 1)
        self.assertTrue(result.sense_pulse)
        self.assertFalse(result.restored)
        again = plane.destructive_read(1, 2, trace=True)
        self.assertEqual(again.observed_bit, 0)
        self.assertFalse(again.sense_pulse)
        self.assertFalse(again.restored)

    def test_zero_restore_is_unnecessary_not_a_failed_write_or_false_pulse(self):
        result = self.plane(0).destructive_read(1, 2, trace=True)
        self.assertEqual([step.core_bit for step in result.trace], [0, 0, 0, 0])
        self.assertEqual(result.trace[2].phase, "RESTORE_SKIP")
        self.assertEqual(result.trace[2].restore_action, "already-zero")
        self.assertEqual([step.sense_pulse for step in result.trace], [None, False, False, False])
        self.assertFalse(result.restored)

    def test_disabled_zero_restore_has_an_explicit_policy_reason(self):
        result = self.plane(0).destructive_read(1, 2, False, trace=True)
        self.assertEqual(result.trace[2].restore_action, "disabled")
        self.assertFalse(result.restored)
        self.assertFalse(result.sense_pulse)

    def test_trace_is_a_tuple_of_frozen_deeply_immutable_snapshots(self):
        result = self.plane().destructive_read(1, 2, trace=True)
        self.assertIsInstance(result.trace, tuple)
        step = result.trace[1]
        with self.assertRaises(FrozenInstanceError):
            step.phase = "COMPLETE"
        self.assertIsInstance(step.bits, tuple)
        self.assertTrue(all(isinstance(row, tuple) for row in step.bits))
        with self.assertRaises(TypeError):
            step.bits[1][2] = 1

    def test_snapshots_survive_later_writes_seeding_and_reads(self):
        plane = self.plane()
        first = plane.destructive_read(1, 2, False, trace=True)
        frozen = repr(first.trace)
        plane.write(1, 2, 1)
        plane.seed_checkerboard()
        second = plane.destructive_read(0, 1, trace=True)
        self.assertEqual(repr(first.trace), frozen)
        self.assertIsNot(first.trace, second.trace)
        self.assertIsNot(first.trace[0].bits, second.trace[0].bits)

    def test_all_bit_policy_address_cases_preserve_every_non_target_core(self):
        for size in (2, 3, 4, 8):
            addresses = {(0, 0), (size - 1, size - 1), (0, size - 1), (size - 1, 0)}
            for row, col in sorted(addresses):
                for bit in (0, 1):
                    for restore in (False, True):
                        with self.subTest(size=size, row=row, col=col, bit=bit, restore=restore):
                            plane = self.plane(bit, row, col, size)
                            before = tuple(tuple(line) for line in plane.bits)
                            result = plane.destructive_read(row, col, restore, trace=True)
                            expected_final = bit if restore else 0
                            self.assertEqual(result.observed_bit, bit)
                            self.assertEqual(result.sense_pulse, bit == 1)
                            self.assertEqual(result.restored, restore and bit == 1)
                            self.assertEqual(plane.bits[row][col], expected_final)
                            self.assertEqual(len(result.trace), 4)
                            for step in result.trace:
                                self.assertEqual((step.row, step.col), (row, col))
                                for r in range(size):
                                    for c in range(size):
                                        if (r, c) != (row, col):
                                            self.assertEqual(step.bits[r][c], before[r][c])
                            self.assertEqual(result.trace[0].bits, before)
                            self.assertEqual(result.trace[-1].bits, tuple(tuple(line) for line in plane.bits))

    def test_selection_geometry_is_unchanged_for_all_selected_addresses(self):
        for size in (2, 4, 8):
            plane = CORE.CorePlane(size)
            for row in range(size):
                for col in range(size):
                    selection = plane.selection_map(row, col)
                    for r in range(size):
                        for c in range(size):
                            self.assertEqual(selection[r][c], 0.5 * ((r == row) + (c == col)))

    def test_real_mutation_order_is_identical_with_trace_on_or_off(self):
        for bit in (0, 1):
            for restore in (False, True):
                runs = []
                for traced in (False, True):
                    changes = []

                    class ObservedRow(list):
                        def __setitem__(self, key, value):
                            changes.append((key, self[key], value))
                            super().__setitem__(key, value)

                    plane = self.plane(bit)
                    plane.bits[1] = ObservedRow(plane.bits[1])
                    result = plane.destructive_read(1, 2, restore, trace=traced)
                    runs.append((changes, result))
                expected = [(2, bit, 0)] + ([(2, 0, 1)] if restore and bit else [])
                self.assertEqual(runs[0][0], expected)
                self.assertEqual(runs[1][0], expected)
                self.assertEqual(
                    [(r.row, r.col, r.observed_bit, r.sense_pulse, r.restored) for _, r in runs],
                    [(1, 2, bit, bit == 1, restore and bit == 1)] * 2,
                )

    def test_invalid_address_fails_before_mutation_or_snapshot_creation(self):
        plane = self.plane()
        initial = tuple(tuple(row) for row in plane.bits)
        for row, col in ((-1, 0), (0, -1), (4, 0), (0, 4)):
            with self.subTest(row=row, col=col):
                with patch.object(CORE, "ReadStep", side_effect=AssertionError("snapshot")):
                    with self.assertRaises(IndexError):
                        plane.destructive_read(row, col, trace=True)
                self.assertEqual(tuple(tuple(row) for row in plane.bits), initial)


class CoreReadTraceCliTests(unittest.TestCase):
    def run_cli(self, *args):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def legacy_output(self, row=1, col=2, restore=True):
        initial = [[(r + c) % 2 for c in range(4)] for r in range(4)]
        observed = initial[row][col]
        render = lambda rows: "\n".join(" ".join(str(value) for value in line) for line in rows)
        selection = "\n".join(
            " ".join(f"{0.5 * ((r == row) + (c == col)):.1f}" for c in range(4))
            for r in range(4)
        )
        output = f"Initial conceptual core plane\n{render(initial)}\n\n"
        output += f"Normalized selection for row={row}, col={col}\n"
        output += f"0.5 = half-selected; 1.0 = selected intersection\n{selection}\n\n"
        output += f"Bit before read: {observed}\nSense pulse observed: {observed == 1}\n"
        output += f"Recovered logical value: {observed}\nRestored after read: {restore and observed == 1}\n\n"
        if not restore:
            initial[row][col] = 0
        output += f"Plane after read sequence\n{render(initial)}\n"
        if not restore and observed == 1:
            output += "\nThe selected 1 is now lost: destructive read was left unrestored.\n"
        return output

    def test_default_stdout_remains_exactly_legacy_output(self):
        self.assertEqual(self.run_cli(), self.legacy_output())

    def test_no_restore_stdout_remains_exactly_legacy_output(self):
        self.assertEqual(self.run_cli("--no-restore"), self.legacy_output(restore=False))

    def test_zero_bit_stdout_remains_exactly_legacy_output(self):
        self.assertEqual(self.run_cli("--row", "0", "--col", "0"), self.legacy_output(0, 0))

    def test_trace_cli_shows_order_and_retained_logical_one_at_clearing(self):
        output = self.run_cli("--trace")
        lines = [line for line in output.splitlines() if line.startswith(("1. ", "2. ", "3. ", "4. "))]
        self.assertEqual(lines, [
            "1. SELECT selected=1 observed=? sense=? restore=pending",
            "2. READ_CLEAR selected=0 observed=1 sense=True restore=pending",
            "3. RESTORE_WRITE selected=1 observed=1 sense=True restore=write-one",
            "4. COMPLETE selected=1 observed=1 sense=True restore=write-one",
        ])
        self.assertIn("snapshots, not measured timing", output)
        self.assertIn("Plane after read sequence", output)

    def test_trace_cli_distinguishes_disabled_restore_and_zero_no_write(self):
        disabled = self.run_cli("--trace", "--no-restore")
        self.assertIn("3. RESTORE_SKIP selected=0 observed=1 sense=True restore=disabled", disabled)
        self.assertIn("The selected 1 is now lost", disabled)
        zero = self.run_cli("--trace", "--row", "0", "--col", "0")
        self.assertIn("3. RESTORE_SKIP selected=0 observed=0 sense=False restore=already-zero", zero)
        self.assertNotIn("RESTORE_WRITE", zero)
        self.assertNotIn("failed", zero.lower())

    def test_help_describes_optional_conceptual_trace(self):
        output = self.run_cli("--help")
        self.assertIn("--trace", output)
        self.assertIn("conceptual", output)


if __name__ == "__main__":
    unittest.main()
