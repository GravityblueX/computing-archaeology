from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "time-sharing" / "time_sharing.py"
README = SCRIPT.with_name("README.md")
CASE_STUDY = ROOT / "case-studies" / "ctss" / "from-batch-to-conversation.md"
SPEC = importlib.util.spec_from_file_location("time_sharing", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - importlib contract
    raise RuntimeError(f"could not load {SCRIPT}")
TIME_SHARING = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TIME_SHARING
SPEC.loader.exec_module(TIME_SHARING)


class TimeSharingLoadTests(unittest.TestCase):
    def test_model_entry_points_reject_non_finite_values(self) -> None:
        invalid_values = (math.nan, math.inf, -math.inf)

        for invalid in invalid_values:
            with self.subTest(entry_point="per_user_offered_load", value=invalid):
                with self.assertRaisesRegex(ValueError, "positive finite"):
                    TIME_SHARING.per_user_offered_load(invalid, 1.0)
            with self.subTest(entry_point="build_requests", value=invalid):
                with self.assertRaisesRegex(ValueError, "positive finite"):
                    TIME_SHARING.build_requests(1, 1, 1.0, invalid)
            with self.subTest(entry_point="simulate_round_robin", value=invalid):
                with self.assertRaisesRegex(ValueError, "positive finite"):
                    TIME_SHARING.simulate_round_robin([], invalid)

    def test_simulator_rejects_non_finite_request_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative finite"):
            TIME_SHARING.simulate_round_robin(
                [TIME_SHARING.Request(math.nan, 0, 0, 1.0)], 1.0
            )
        with self.assertRaisesRegex(ValueError, "positive finite"):
            TIME_SHARING.simulate_round_robin(
                [TIME_SHARING.Request(0.0, 0, 0, math.inf)], 1.0
            )

    def test_nominal_load_matches_fixed_arrivals_at_saturation(self) -> None:
        requests = TIME_SHARING.build_requests(
            users=1,
            rounds=4,
            request_interval=1.0,
            cpu_burst=1.0,
        )
        metrics = TIME_SHARING.simulate_round_robin(requests, quantum=1.0)

        self.assertEqual(
            [request.arrival for request in requests], [0.0, 1.0, 2.0, 3.0]
        )
        self.assertEqual(TIME_SHARING.per_user_offered_load(1.0, 1.0), 1.0)
        self.assertEqual(TIME_SHARING.offered_load(1, 1.0, 1.0), 1.0)
        self.assertEqual(metrics.completed, 4)
        self.assertEqual(metrics.cpu_utilization, 1.0)
        self.assertEqual(metrics.makespan, 4.0)

    def test_load_boundary_tracks_adjacent_cpu_bursts(self) -> None:
        below = math.nextafter(1.0, 0.0)
        above = math.nextafter(1.0, math.inf)

        self.assertLess(TIME_SHARING.offered_load(1, below, 1.0), 1.0)
        self.assertEqual(TIME_SHARING.offered_load(1, 1.0, 1.0), 1.0)
        self.assertGreater(TIME_SHARING.offered_load(1, above, 1.0), 1.0)

    def test_default_nominal_load_matches_default_arrival_rate(self) -> None:
        requests = TIME_SHARING.build_requests(
            users=20,
            rounds=2,
            request_interval=10.0,
            cpu_burst=0.05,
        )
        first_interval = [request for request in requests if request.arrival < 10.0]

        self.assertEqual(len(first_interval), 20)
        self.assertEqual(TIME_SHARING.per_user_offered_load(0.05, 10.0), 0.005)
        self.assertEqual(TIME_SHARING.offered_load(20, 0.05, 10.0), 0.1)
        self.assertAlmostEqual(
            sum(request.cpu for request in first_interval) / 10.0,
            TIME_SHARING.offered_load(20, 0.05, 10.0),
        )

    def test_saturation_cli_reproducer_reports_queueing_pressure(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--users",
                "1",
                "--rounds",
                "4",
                "--think",
                "1",
                "--cpu",
                "1",
                "--quantum",
                "1",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn(
            "one user's offered load:      100.000% of one CPU", completed.stdout
        )
        self.assertIn(
            "aggregate offered load:      100.000% of one CPU", completed.stdout
        )
        self.assertIn("observed utilization:100.000%", completed.stdout)
        self.assertIn(
            "Interpretation: offered demand reaches/exceeds one CPU; "
            "queueing pressure is expected.",
            completed.stdout,
        )

    def test_think_help_defines_an_open_loop_request_interval(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--think SECONDS", completed.stdout)
        self.assertIn(
            "fixed seconds between request starts (open-loop)", completed.stdout
        )

    def test_cli_rejects_non_finite_values_without_hanging(self) -> None:
        for flag in ("--think", "--cpu", "--quantum"):
            for value in ("nan", "inf", "-inf"):
                with self.subTest(flag=flag, value=value):
                    completed = subprocess.run(
                        [sys.executable, "-B", str(SCRIPT), f"{flag}={value}"],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                    )

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("must be positive finite numbers", completed.stderr)

    def test_companion_docs_share_the_open_loop_contract(self) -> None:
        readme = README.read_text(encoding="utf-8")
        case_study = CASE_STUDY.read_text(encoding="utf-8")
        companion_section = case_study.split(
            "## Reconstruction: why slow humans create multiplexing opportunity", 1
        )[1].split("## What breaks the illusion", 1)[0]

        for document in (readme, companion_section):
            self.assertIn("start-to-start", document)
            self.assertIn("open-loop", document)
        self.assertNotIn("human think time", companion_section)
        self.assertNotIn("reserving a machine", companion_section)

    def test_default_output_reports_request_interval_and_keeps_simulation(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            completed.stdout,
            "Interactive sharing toy model\n"
            "users:                 20\n"
            "requests/user:         20\n"
            "request-start interval: 10.000 s\n"
            "CPU burst/request:     0.050 s\n"
            "round-robin quantum:   0.020 s\n"
            "\n"
            "one user's offered load:        0.500% of one CPU\n"
            "aggregate offered load:       10.000% of one CPU\n"
            "\n"
            "simulated shared CPU\n"
            "  completed requests:  400\n"
            "  mean response time:  0.0500 s\n"
            "  max response time:   0.0500 s\n"
            "  observed utilization: 10.023%\n"
            "  modeled makespan:    199.550 s\n"
            "\n"
            "Interpretation: substantial spare CPU capacity remains in this toy workload.\n",
        )


class ClosedLoopTimeSharingTests(unittest.TestCase):
    def simulate(self, users=2, rounds=2, pause=1.0, cpu=1.0, quantum=0.5, **kwargs):
        return TIME_SHARING.simulate_closed_loop(
            users, rounds, pause, cpu, quantum, **kwargs
        )

    def test_single_user_pauses_only_after_each_completed_response(self):
        result = self.simulate(users=1, rounds=3, pause=2.0, quantum=1.0)
        self.assertEqual([r.arrival for r in result.completions], [0, 3, 6])
        self.assertEqual([r.completion for r in result.completions], [1, 4, 7])
        self.assertEqual(result.metrics.completed, 3)
        self.assertEqual(result.metrics.mean_response, 1)
        self.assertEqual(result.metrics.max_response, 1)
        self.assertEqual(result.metrics.makespan, 7)
        self.assertEqual(result.busy_time, 3)
        self.assertEqual(result.metrics.cpu_utilization, 3 / 7)
        self.assertEqual(result.peak_outstanding, 1)
        self.assertEqual(result.slices, ())

    def test_shared_initial_arrivals_expose_the_open_closed_distinction(self):
        closed = self.simulate(trace=True)
        self.assertEqual(
            [(r.user, r.sequence, r.arrival, r.completion) for r in closed.completions],
            [(0, 0, 0, 1.5), (1, 0, 0.5, 2), (0, 1, 2.5, 4), (1, 1, 3, 4.5)],
        )
        self.assertEqual(closed.metrics.mean_response, 1.5)
        self.assertEqual(closed.metrics.max_response, 1.5)
        self.assertEqual(closed.metrics.makespan, 4.5)
        self.assertEqual(closed.metrics.cpu_utilization, 8 / 9)
        self.assertEqual(closed.busy_time, 4)
        self.assertEqual(closed.peak_outstanding, 2)
        self.assertEqual(len(closed.slices), 8)
        requests = TIME_SHARING.build_requests(2, 2, 1, 1)
        self.assertEqual([r.arrival for r in requests], [0, 0.5, 1, 1.5])
        opened = TIME_SHARING.simulate_round_robin(requests, 0.5)
        self.assertEqual(opened.mean_response, 2.125)
        self.assertEqual(opened.max_response, 2.5)
        self.assertEqual(opened.makespan, 4)

    def test_zero_pause_resubmits_after_completion_without_duplicate_users(self):
        result = self.simulate(pause=0, trace=True)
        self.assertEqual(
            [(r.user, r.sequence, r.arrival, r.completion) for r in result.completions],
            [(0, 0, 0, 1.5), (1, 0, 0, 2), (0, 1, 1.5, 3.5), (1, 1, 2, 4)],
        )
        self.assertEqual(result.metrics.mean_response, 15 / 8)
        self.assertEqual(result.metrics.cpu_utilization, 1)
        self.assertEqual(result.peak_outstanding, 2)

    def test_waking_user_enters_before_unfinished_request_is_requeued(self):
        result = self.simulate(users=3, pause=1, cpu=2, quantum=1, trace=True)
        self.assertEqual([r.completion for r in result.completions], [4, 5, 6, 10, 11, 12])
        self.assertEqual([r.arrival for r in result.completions[3:]], [5, 6, 7])
        self.assertEqual(
            [(s.user, s.sequence, s.start) for s in result.slices if 6 <= s.start <= 9],
            [(0, 1, 6), (1, 1, 7), (2, 1, 8), (0, 1, 9)],
        )
        self.assertAlmostEqual(result.metrics.mean_response, 29 / 6)
        self.assertAlmostEqual(result.metrics.max_response, 16 / 3)

    def test_peak_outstanding_distinguishes_handoff_from_actual_overlap(self):
        for rounds in (1, 3):
            with self.subTest(rounds=rounds):
                handoff = self.simulate(rounds=rounds, pause=2, quantum=1, trace=True)
                self.assertEqual(handoff.peak_outstanding, 1)
                self.assertEqual(handoff.metrics.max_response, 1)
        overlapping = self.simulate(rounds=1, pause=1, quantum=1, trace=True)
        self.assertEqual(overlapping.peak_outstanding, 2)
        self.assertEqual(overlapping.completions[0].completion, 1)
        self.assertEqual(overlapping.completions[1].arrival, 0.5)

    def test_tiny_time_units_do_not_erase_positive_service_or_admit_early(self):
        scale = 2.0 ** -44
        result = self.simulate(pause=scale, cpu=scale, quantum=scale / 2, trace=True)
        self.assertEqual([r.arrival / scale for r in result.completions], [0, 0.5, 2.5, 3])
        self.assertEqual([r.completion / scale for r in result.completions], [1.5, 2, 4, 4.5])
        self.assertEqual(result.metrics.mean_response / scale, 1.5)
        self.assertEqual(result.metrics.cpu_utilization, 8 / 9)
        self.assertEqual(result.busy_time / scale, 4)

    def test_nondivisible_quantum_retains_all_cpu_and_has_one_outstanding_per_user(self):
        result = self.simulate(users=4, rounds=5, pause=0.7, cpu=0.31, quantum=0.1, trace=True)
        self.assertEqual(result.metrics.completed, 20)
        self.assertLessEqual(result.peak_outstanding, 4)
        self.assertAlmostEqual(result.busy_time, 20 * 0.31)
        for user in range(4):
            completed = sorted((r for r in result.completions if r.user == user), key=lambda r: r.sequence)
            self.assertEqual([r.sequence for r in completed], list(range(5)))
            for previous, current in zip(completed, completed[1:]):
                self.assertEqual(current.arrival, previous.completion + 0.7)
            for request in completed:
                service = [s for s in result.slices if (s.user, s.sequence) == (user, request.sequence)]
                self.assertAlmostEqual(math.fsum(s.cpu for s in service), request.cpu)
                self.assertGreaterEqual(service[0].start, request.arrival)
                self.assertEqual(service[-1].end, request.completion)
                self.assertTrue(all(0 < s.cpu <= 0.1 for s in service))
        for left, right in zip(result.slices, result.slices[1:]):
            self.assertLessEqual(left.end, right.start)

    def test_decimal_quanta_do_not_create_spurious_leftover_service(self):
        for users, cpu, quantum, count in ((1, 0.2, 0.05, 4), (2, 0.2, 0.05, 8), (2, 1, 0.1, 20)):
            with self.subTest(users=users, cpu=cpu, quantum=quantum):
                result = self.simulate(users=users, rounds=1, pause=0, cpu=cpu, quantum=quantum, trace=True)
                self.assertEqual(result.metrics.completed, users)
                self.assertEqual(len(result.slices), count)
                self.assertAlmostEqual(result.busy_time, users * cpu)
                for user in range(users):
                    self.assertEqual(math.fsum(s.cpu for s in result.slices if s.user == user), cpu)

    def test_trace_is_observational_and_calls_do_not_share_state(self):
        plain = self.simulate()
        traced = self.simulate(trace=True)
        self.assertEqual(plain.metrics, traced.metrics)
        self.assertEqual(plain.completions, traced.completions)
        self.assertEqual(plain.busy_time, traced.busy_time)
        traced.metrics.completed = -1
        self.assertEqual(self.simulate().metrics.completed, 4)

    def test_mean_preserves_subnormal_responses_and_avoids_sum_overflow(self):
        tiny = math.ulp(0.0)
        small = self.simulate(users=1, pause=0, cpu=tiny, quantum=tiny)
        self.assertEqual(small.metrics.mean_response, tiny)
        self.assertEqual(small.metrics.max_response, tiny)
        self.assertEqual(small.metrics.makespan, 2 * tiny)
        large = self.simulate(rounds=1, pause=0, cpu=8e307, quantum=8e307)
        self.assertEqual(large.metrics.mean_response, 1.2e308)
        self.assertEqual(large.metrics.makespan, 1.6e308)
        self.assertEqual(large.metrics.cpu_utilization, 1)

    def test_count_and_duration_inputs_are_validated(self):
        for name in ("users", "rounds"):
            for invalid in (0, -1, 1.5, True, "2"):
                with self.subTest(name=name, value=invalid), self.assertRaisesRegex(ValueError, "positive integer"):
                    self.simulate(**{name: invalid})
        for name in ("pause", "cpu", "quantum"):
            for invalid in (math.nan, math.inf, -math.inf, -1, True, "1"):
                with self.subTest(name=name, value=invalid), self.assertRaisesRegex(ValueError, "finite"):
                    self.simulate(**{name: invalid})
        for name in ("cpu", "quantum"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.simulate(**{name: 0})

    def test_unrepresentable_time_and_service_progress_fail_explicitly(self):
        cases = [
            {"users": 1, "rounds": 2, "pause": 2.0 ** 54, "cpu": 1, "quantum": 1},
            {"users": 1, "rounds": 2, "pause": 1e308, "cpu": 1e308, "quantum": 1e308},
            {"users": 1, "rounds": 1, "cpu": 1, "quantum": 2.0 ** -60},
            {"users": 2, "pause": math.ulp(0.0)},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "representable"):
                self.simulate(**case)

    def test_cli_pause_mode_discloses_finite_run_metrics_and_completion_trace(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--users", "2", "--rounds", "2", "--pause", "1", "--cpu", "1", "--quantum", "0.5", "--trace"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Closed-loop interactive sharing toy model", result.stdout)
        self.assertIn("post-response pause:    1.000 s", result.stdout)
        self.assertIn("mean response time:  1.5000 s", result.stdout)
        self.assertIn("modeled makespan:    4.500 s", result.stdout)
        self.assertIn("peak outstanding:    2 / 2 users", result.stdout)
        self.assertIn("completion trace", result.stdout)
        self.assertNotIn("offered load", result.stdout)

    def test_cli_rejects_ambiguous_modes_and_invalid_pause(self):
        for args in (["--think", "1", "--pause", "1"], ["--trace"], ["--pause=-1"], ["--pause=nan"], ["--pause=inf"]):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
