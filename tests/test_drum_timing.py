from __future__ import annotations

import argparse
from dataclasses import FrozenInstanceError, astuple, fields
import importlib.util
import inspect
import itertools
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "drum-timing" / "drum_timing.py"
SPEC = importlib.util.spec_from_file_location("drum_timing", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT}")
DRUM = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRUM
SPEC.loader.exec_module(DRUM)

DEFAULT_STDOUT = """drum: 12500 rpm, 50 slots/revolution
time per slot: 96.000 us
instruction latencies: [3, 8, 2, 5, 4, 7]
consecutive placement: [0, 1, 2, 3, 4, 5]
timing-aware placement: [0, 3, 11, 13, 18, 22]

consecutive
  execution:      290 slots (27.840 ms)
  waiting:       2710 slots (260.160 ms)
  total:         3000 slots (288.000 ms)
  useful-time fraction:   9.67%

timing-aware
  execution:      290 slots (27.840 ms)
  waiting:        210 slots (20.160 ms)
  total:          500 slots (48.000 ms)
  useful-time fraction:  58.00%

saved by placement in this model: 2500 slots (240.000 ms)
"""


def tick_oracle(latencies, placement, slots, loops):
    """Advance one physical slot at a time, independently of the model's jumps."""
    time = 0
    phase = placement[0]
    execution = 0
    waiting = 0
    rows = []
    for loop in range(1, loops + 1):
        for index, latency in enumerate(latencies):
            start, before = time, phase
            for _ in range(latency):
                phase = (phase + 1) % slots
                time += 1
                execution += 1
            finish_phase = phase
            next_index = (index + 1) % len(placement)
            target = placement[next_index]
            wait = 0
            while phase != target:
                phase = (phase + 1) % slots
                time += 1
                wait += 1
                waiting += 1
            rows.append((loop, index, before, start, latency, finish_phase,
                         next_index, target, wait, time, next_index == 0))
    return execution, waiting, rows


class DrumTimingTests(unittest.TestCase):
    def cli(self, *args, success=True):
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args], cwd=ROOT,
            capture_output=True, text=True, timeout=10, check=False,
        )
        if success:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
        else:
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertEqual(completed.stdout, "")
            self.assertNotIn("Traceback", completed.stderr)
        return completed

    def test_legacy_api_and_result_fields_are_preserved(self):
        self.assertEqual(list(inspect.signature(DRUM.run_loop).parameters),
                         ["latencies", "placement", "slots", "loops"])
        self.assertEqual([field.name for field in fields(DRUM.RunResult)],
                         ["execution_slots", "wait_slots"])
        self.assertEqual(DRUM.RunResult(0, 0).utilization, 0.0)
        self.assertEqual(DRUM.run_loop([1], [0], 3, 0), DRUM.RunResult(0, 0))
        with self.assertRaisesRegex(ValueError, "equal length"):
            DRUM.run_loop([1], [0, 1], 3, 1)

    def test_hand_calculated_nine_versus_six_slots(self):
        latencies = [1, 2, 2]
        self.assertEqual(DRUM.greedy_placement(latencies, 3), [0, 1, 2])
        self.assertEqual(DRUM.naive_placement(3, 3), [0, 1, 2])
        self.assertEqual(DRUM.run_loop(latencies, [0, 1, 2], 3, 1), DRUM.RunResult(5, 4))
        self.assertEqual(DRUM.run_loop(latencies, [0, 2, 1], 3, 1), DRUM.RunResult(5, 1))

    def test_exact_handwritten_transition_rows(self):
        expected = {
            (0, 1, 2): [
                (1, 0, 0, 0, 1, 1, 1, 1, 0, 1, False),
                (1, 1, 1, 1, 2, 0, 2, 2, 2, 5, False),
                (1, 2, 2, 5, 2, 1, 0, 0, 2, 9, True),
            ],
            (0, 2, 1): [
                (1, 0, 0, 0, 1, 1, 1, 2, 1, 2, False),
                (1, 1, 2, 2, 2, 1, 2, 1, 0, 4, False),
                (1, 2, 1, 4, 2, 0, 0, 0, 0, 6, True),
            ],
        }
        for placement, rows in expected.items():
            with self.subTest(placement=placement):
                traced = DRUM.trace_loop([1, 2, 2], list(placement), 3, 1)
                self.assertEqual([astuple(step) for step in traced.steps], rows)

    def test_trace_components_sum_to_the_same_run(self):
        traced = DRUM.trace_loop([2, 5, 1], [3, 0, 2], 7, 4)
        self.assertEqual(traced.result, DRUM.run_loop([2, 5, 1], [3, 0, 2], 7, 4))
        self.assertEqual(sum(step.execution_slots for step in traced.steps), traced.result.execution_slots)
        self.assertEqual(sum(step.wait_slots for step in traced.steps), traced.result.wait_slots)
        self.assertEqual(traced.steps[-1].next_ready_slots, traced.result.total_slots)
        for previous, following in zip(traced.steps, traced.steps[1:]):
            self.assertEqual(previous.next_ready_slots, following.start_slots)
            self.assertEqual(previous.next_slot, following.phase_before)
            self.assertEqual(previous.next_instruction, following.instruction)

    def test_final_loop_still_includes_its_closing_wait(self):
        traced = DRUM.trace_loop([1, 2, 2], [0, 1, 2], 3, 3)
        self.assertEqual(traced.result, DRUM.RunResult(15, 12))
        self.assertEqual([step.next_ready_slots for step in traced.steps if step.closes_loop], [9, 18, 27])
        self.assertEqual(traced.steps[-1].start_slots + traced.steps[-1].execution_slots, 25)
        self.assertEqual(traced.steps[-1].wait_slots, 2)
        self.assertEqual(traced.steps[-1].next_ready_slots, 27)

    def test_rotating_all_addresses_preserves_time_and_shifts_phases(self):
        original = DRUM.trace_loop([1, 2, 2], [0, 2, 1], 3, 2)
        for offset in range(3):
            shifted = DRUM.trace_loop([1, 2, 2], [(slot + offset) % 3 for slot in [0, 2, 1]], 3, 2)
            self.assertEqual(shifted.result, original.result)
            for before, after in zip(original.steps, shifted.steps):
                self.assertEqual(after.phase_before, (before.phase_before + offset) % 3)
                self.assertEqual(after.phase_after_execution, (before.phase_after_execution + offset) % 3)
                self.assertEqual(after.next_slot, (before.next_slot + offset) % 3)
                self.assertEqual((after.start_slots, after.execution_slots, after.wait_slots, after.next_ready_slots),
                                 (before.start_slots, before.execution_slots, before.wait_slots, before.next_ready_slots))

    def test_whole_and_multiple_revolutions_keep_execution_demand(self):
        traced = DRUM.trace_loop([6, 3], [2, 0], 3, 2)
        self.assertEqual(traced.result, DRUM.RunResult(18, 6))
        self.assertEqual([step.execution_slots for step in traced.steps], [6, 3, 6, 3])
        self.assertEqual([step.phase_after_execution for step in traced.steps], [2, 0, 2, 0])
        self.assertEqual(DRUM.run_loop([6], [2], 3, 1), DRUM.RunResult(6, 0))

    def test_one_slot_and_one_instruction_have_no_extra_wait(self):
        DRUM.validate_placement([0], 1, 1)
        traced = DRUM.trace_loop([4], [0], 1, 2)
        self.assertEqual(traced.result, DRUM.RunResult(8, 0))
        self.assertTrue(all(step.closes_loop and step.wait_slots == 0 for step in traced.steps))

    def test_inputs_and_separate_trace_runs_are_isolated(self):
        latencies, placement = [1, 2, 2], [0, 2, 1]
        first = DRUM.trace_loop(latencies, placement, 3, 1)
        second = DRUM.trace_loop(latencies, placement, 3, 1)
        self.assertEqual(first, second)
        self.assertIsNot(first.steps, second.steps)
        self.assertEqual(latencies, [1, 2, 2])
        self.assertEqual(placement, [0, 2, 1])
        latencies[0] = 99
        placement[0] = 2
        self.assertEqual(first.steps[0].execution_slots, 1)
        self.assertEqual(first.steps[0].phase_before, 0)

    def test_trace_snapshots_and_containers_are_immutable(self):
        traced = DRUM.trace_loop([1], [0], 3, 1)
        self.assertIsInstance(traced.steps, tuple)
        with self.assertRaises(FrozenInstanceError):
            traced.steps[0].wait_slots = 99
        with self.assertRaises(FrozenInstanceError):
            traced.result = DRUM.RunResult(99, 99)
        with self.assertRaises(FrozenInstanceError):
            traced.result.wait_slots = 99

    def test_plain_run_allocates_no_instruction_snapshots(self):
        with mock.patch.object(DRUM, "InstructionStep", side_effect=AssertionError("unrequested snapshot")):
            self.assertEqual(DRUM.run_loop([1, 2, 2], [0, 2, 1], 3, 2), DRUM.RunResult(10, 2))

    def test_snapshot_constructor_observes_live_transition_state(self):
        constructor = DRUM.InstructionStep
        observed = []

        def observe(**values):
            frame = inspect.currentframe()
            while frame is not None and frame.f_code.co_name != "_run_loop":
                frame = frame.f_back
            self.assertIsNotNone(frame, "snapshot constructed outside the actual runner")
            state = frame.f_locals
            self.assertEqual(values["phase_after_execution"], state["position"])
            self.assertEqual(values["next_ready_slots"], state["execution"] + state["waiting"])
            self.assertEqual(values["next_slot"], state["target"])
            self.assertEqual(values["wait_slots"], state["wait"])
            observed.append(values)
            return constructor(**values)

        with mock.patch.object(DRUM, "InstructionStep", side_effect=observe):
            traced = DRUM.trace_loop([1, 2, 2], [0, 2, 1], 3, 2)
        self.assertEqual(len(observed), 6)
        self.assertEqual([step.next_ready_slots for step in traced.steps], [2, 4, 6, 8, 10, 12])

    def test_invalid_user_layouts_are_rejected(self):
        cases = [([], 3, 3), ([0, 1], 3, 3), ([0, 1, 2, 3], 3, 4),
                 ([0, 1, 1], 3, 3), ([0, -1, 2], 3, 3), ([0, 1, 3], 3, 3),
                 ([True, 1, 2], 3, 3), ([0.0, 1, 2], 3, 3), (["0", 1, 2], 3, 3)]
        for placement, count, slots in cases:
            with self.subTest(placement=placement), self.assertRaises(ValueError):
                DRUM.validate_placement(placement, count, slots)

    def test_placement_parser_rejects_empty_and_noninteger_tokens(self):
        for text in ["", " ", ",", "0,,1", "0,1,", ",0,1", "0,1.5,2", "0,x,2"]:
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                DRUM.parse_placement(text)

    def test_user_placement_preserves_order_and_allows_unused_slots(self):
        placement = DRUM.parse_placement(" 2, 0, 4 ")
        self.assertEqual(placement, [2, 0, 4])
        DRUM.validate_placement(placement, 3, 7)
        self.assertEqual(placement, [2, 0, 4])

    def test_cli_invalid_custom_layouts_have_clear_errors(self):
        for placement in ["", "0,1", "0,1,1", "0,-1,2", "0,1,3", "0,x,2", "0,,2", "0,1,2,"]:
            with self.subTest(placement=placement):
                completed = self.cli("--slots", "3", "--latencies", "1,2,2", "--loops", "1",
                                     "--placement=" + placement, success=False)
                self.assertIn("placement", completed.stderr)

    def test_exact_original_default_stdout(self):
        self.assertEqual(self.cli().stdout, DEFAULT_STDOUT)

    def test_custom_layout_and_trace_show_the_hand_calculated_lesson(self):
        args = ["--slots", "3", "--latencies", "1,2,2", "--loops", "1"]
        baseline = self.cli(*args).stdout
        custom = self.cli(*args, "--placement", "0,2,1").stdout
        self.assertTrue(custom.startswith(baseline))
        self.assertIn("user placement: [0, 2, 1]", custom)
        self.assertIn("  total:            6 slots", custom)
        self.assertNotIn(" trace (", custom)
        traced = self.cli(*args, "--placement", "0,2,1", "--trace").stdout
        self.assertTrue(traced.startswith(custom))
        self.assertEqual(traced.count(" trace (integer slots"), 3)
        custom_rows = traced.split("user placement trace", 1)[1].splitlines()[2:]
        self.assertEqual([row.split() for row in custom_rows], [
            ["1", "0", "0", "0", "1", "1", "2", "1", "2", "no"],
            ["1", "1", "2", "2", "2", "1", "1", "0", "4", "no"],
            ["1", "2", "1", "4", "2", "0", "0", "0", "6", "yes"],
        ])
        self.assertIn("even the last loop", traced)
        self.assertIn("not SOAP or measured IBM 650", traced)

    def test_trace_without_custom_layout_keeps_both_original_summaries(self):
        traced = self.cli("--trace").stdout
        self.assertTrue(traced.startswith(DEFAULT_STDOUT))
        self.assertEqual(traced.count(" trace (integer slots"), 2)
        self.assertNotIn("user placement", traced)

    def test_exhaustive_small_layouts_against_independent_tick_oracle(self):
        cases = 0
        for slots in range(1, 6):
            for count in range(1, min(slots, 3) + 1):
                for placement in itertools.permutations(range(slots), count):
                    for latencies in itertools.product(sorted({1, slots, slots + 1}), repeat=count):
                        for loops in (1, 2):
                            execution, waiting, rows = tick_oracle(latencies, placement, slots, loops)
                            traced = DRUM.trace_loop(list(latencies), list(placement), slots, loops)
                            self.assertEqual(traced.result, DRUM.RunResult(execution, waiting))
                            self.assertEqual(traced.result, DRUM.run_loop(list(latencies), list(placement), slots, loops))
                            self.assertEqual([astuple(step) for step in traced.steps], rows)
                            cases += 1
        self.assertEqual(cases, 5668)


if __name__ == "__main__":
    unittest.main()
