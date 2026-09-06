from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "tty-budget" / "tty_budget.py"
SPEC = importlib.util.spec_from_file_location("tty_budget", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - importlib contract
    raise RuntimeError(f"could not load {SCRIPT}")
TTY_BUDGET = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TTY_BUDGET
SPEC.loader.exec_module(TTY_BUDGET)


class TtyBudgetTests(unittest.TestCase):
    def test_model_entry_points_reject_non_finite_rates(self) -> None:
        entry_points = (
            (
                "chars_per_second baud",
                lambda value: TTY_BUDGET.chars_per_second(value, 11.0),
            ),
            (
                "chars_per_second frame bits",
                lambda value: TTY_BUDGET.chars_per_second(110.0, value),
            ),
            (
                "transmit_seconds baud",
                lambda value: TTY_BUDGET.transmit_seconds(12, value, 11.0),
            ),
            (
                "transmit_seconds frame bits",
                lambda value: TTY_BUDGET.transmit_seconds(12, 110.0, value),
            ),
        )
        for name, entry_point in entry_points:
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(entry_point=name, value=value):
                    with self.assertRaisesRegex(ValueError, "positive finite"):
                        entry_point(value)

    def test_cli_rejects_non_finite_rates_before_printing(self) -> None:
        for flag in ("--baud", "--frame-bits"):
            for value in ("nan", "inf", "-inf"):
                with self.subTest(flag=flag, value=value):
                    completed = subprocess.run(
                        [sys.executable, "-B", str(SCRIPT), f"{flag}={value}"],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                    )

                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(completed.stdout, "")
                    self.assertIn(
                        f"{flag} must be a positive finite number",
                        completed.stderr,
                    )
                    self.assertNotIn("Traceback", completed.stderr)

    def test_model_rejects_unrepresentable_effective_rates(self) -> None:
        smallest = math.ulp(0.0)
        largest = sys.float_info.max
        for name, baud, frame_bits in (
            ("underflow", smallest, largest),
            ("overflow", largest, smallest),
        ):
            for entry_point in (
                TTY_BUDGET.chars_per_second,
                lambda left, right: TTY_BUDGET.transmit_seconds(12, left, right),
            ):
                with self.subTest(case=name, entry_point=entry_point.__name__):
                    with self.assertRaisesRegex(
                        ValueError, "positive finite character rate"
                    ):
                        entry_point(baud, frame_bits)

    def test_cli_rejects_unrepresentable_effective_rates_before_printing(self) -> None:
        smallest = math.ulp(0.0)
        largest = sys.float_info.max
        for name, baud, frame_bits in (
            ("underflow", smallest, largest),
            ("overflow", largest, smallest),
        ):
            with self.subTest(case=name):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(SCRIPT),
                        f"--baud={baud!r}",
                        f"--frame-bits={frame_bits!r}",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertIn(
                    "baud and frame bits must produce a positive finite character rate",
                    completed.stderr,
                )
                self.assertNotIn("Traceback", completed.stderr)

    def test_model_rejects_unrepresentable_transmission_durations(self) -> None:
        for name, characters, baud in (
            ("floating-point overflow", 12, math.ulp(0.0)),
            ("integer conversion overflow", 10**1000, 110.0),
        ):
            with self.subTest(case=name):
                with self.assertRaisesRegex(ValueError, "finite transmission duration"):
                    TTY_BUDGET.transmit_seconds(characters, baud, 1.0)

    def test_cli_rejects_unrepresentable_durations_before_printing(self) -> None:
        for name, arguments in (
            (
                "first default example",
                [f"--baud={math.ulp(0.0)!r}", "--frame-bits=1"],
            ),
            (
                "later default example",
                ["--baud=1e-306", "--frame-bits=1"],
            ),
            (
                "custom text",
                ["--baud=2e-305", "--frame-bits=1", f"--text={'x' * 4000}"],
            ),
        ):
            with self.subTest(case=name):
                completed = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), *arguments],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertIn("finite transmission duration", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_cli_rejects_oversized_character_counts_before_printing(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                f"--characters={10**1000}",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=2.0,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("finite transmission duration", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_positive_finite_rates_keep_nominal_results(self) -> None:
        self.assertEqual(TTY_BUDGET.chars_per_second(110.0, 11.0), 10.0)
        self.assertEqual(TTY_BUDGET.transmit_seconds(0, 110.0, 11.0), 0.0)
        self.assertAlmostEqual(
            TTY_BUDGET.transmit_seconds(12, 110.0, 11.0),
            1.2,
        )

        for invalid in (0.0, -1.0):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(ValueError, "positive finite"):
                    TTY_BUDGET.chars_per_second(invalid, 11.0)
                with self.assertRaisesRegex(ValueError, "positive finite"):
                    TTY_BUDGET.chars_per_second(110.0, invalid)

    def test_default_cli_output_keeps_model_33_assumptions(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("baud=110, frame=11 signal units/character", completed.stdout)
        self.assertIn("effective rate: 10.000 characters/second", completed.stdout)
        self.assertIn("80x24 screenful", completed.stdout)
        self.assertIn("3m 12.0s", completed.stdout)


if __name__ == "__main__":
    unittest.main()
