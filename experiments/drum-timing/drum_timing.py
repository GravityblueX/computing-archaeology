#!/usr/bin/env python3
"""Tiny rotational-memory timing model.

This is a teaching model for the geometry of a drum-resident instruction
sequence. It is not an IBM 650 emulator and does not reproduce SOAP.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class RunResult:
    execution_slots: int
    wait_slots: int

    @property
    def total_slots(self) -> int:
        return self.execution_slots + self.wait_slots

    @property
    def utilization(self) -> float:
        if self.total_slots == 0:
            return 0.0
        return self.execution_slots / self.total_slots


@dataclass(frozen=True)
class InstructionStep:
    """One observed execution and the wait for the next instruction."""

    loop: int
    instruction: int
    phase_before: int
    start_slots: int
    execution_slots: int
    phase_after_execution: int
    next_instruction: int
    next_slot: int
    wait_slots: int
    next_ready_slots: int
    closes_loop: bool


@dataclass(frozen=True)
class TracedRun:
    result: RunResult
    steps: tuple[InstructionStep, ...]


def parse_placement(text: str) -> list[int]:
    try:
        return [int(part.strip()) for part in text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "placement must be comma-separated integers without empty slots"
        ) from exc


def validate_placement(placement: list[int], count: int, slots: int) -> None:
    """Validate a user layout; instruction order itself is not changed."""
    if len(placement) != count:
        raise ValueError("--placement must give one slot per instruction")
    if any(type(slot) is not int or not 0 <= slot < slots for slot in placement):
        raise ValueError("--placement slots must be integers inside the drum")
    if len(set(placement)) != len(placement):
        raise ValueError("--placement slots must be distinct")


def parse_latencies(text: str) -> list[int]:
    values = [int(part.strip()) for part in text.split(",") if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError("provide at least one latency")
    if any(value < 1 for value in values):
        raise argparse.ArgumentTypeError("latencies must be positive integers")
    return values


def naive_placement(count: int, slots: int) -> list[int]:
    if count > slots:
        raise ValueError("this simple model requires instruction count <= drum slots")
    return list(range(count))


def greedy_placement(latencies: list[int], slots: int) -> list[int]:
    """Place each next instruction near when the previous one finishes.

    A simple first-fit policy is used if the ideal slot is already occupied.
    """
    if len(latencies) > slots:
        raise ValueError("this simple model requires instruction count <= drum slots")

    placement = [0]
    occupied = {0}

    for latency in latencies[:-1]:
        ideal = (placement[-1] + latency) % slots
        chosen = None
        for offset in range(slots):
            candidate = (ideal + offset) % slots
            if candidate not in occupied:
                chosen = candidate
                break
        assert chosen is not None
        placement.append(chosen)
        occupied.add(chosen)

    return placement


def run_loop(
    latencies: list[int],
    placement: list[int],
    slots: int,
    loops: int,
) -> RunResult:
    return _run_loop(latencies, placement, slots, loops, None)


def trace_loop(
    latencies: list[int],
    placement: list[int],
    slots: int,
    loops: int,
) -> TracedRun:
    """Run the same transitions, retaining immutable observations on request."""
    steps: list[InstructionStep] = []
    result = _run_loop(latencies, placement, slots, loops, steps)
    return TracedRun(result, tuple(steps))


def _run_loop(
    latencies: list[int],
    placement: list[int],
    slots: int,
    loops: int,
    steps: list[InstructionStep] | None,
) -> RunResult:
    if len(latencies) != len(placement):
        raise ValueError("latency and placement lists must have equal length")

    position = placement[0]
    execution = 0
    waiting = 0

    for loop in range(loops):
        for index, latency in enumerate(latencies):
            if steps is not None:
                start_slots = execution + waiting
                phase_before = position
            execution += latency
            position = (position + latency) % slots

            next_index = (index + 1) % len(latencies)
            target = placement[next_index]
            wait = (target - position) % slots
            waiting += wait
            if steps is not None:
                steps.append(InstructionStep(
                    loop=loop + 1,
                    instruction=index,
                    phase_before=phase_before,
                    start_slots=start_slots,
                    execution_slots=latency,
                    phase_after_execution=position,
                    next_instruction=next_index,
                    next_slot=target,
                    wait_slots=wait,
                    next_ready_slots=execution + waiting,
                    closes_loop=next_index == 0,
                ))
            position = target

    return RunResult(execution, waiting)


def print_trace(label: str, traced: TracedRun) -> None:
    print(f"{label} trace (integer slots; loop numbers start at 1)")
    print("loop  instruction  slot  start  execute  phase-end  next-slot  wait  ready  closes-loop")
    for step in traced.steps:
        print(
            f"{step.loop:>4}  {step.instruction:>11}  {step.phase_before:>4}  "
            f"{step.start_slots:>5}  {step.execution_slots:>7}  "
            f"{step.phase_after_execution:>9}  {step.next_slot:>9}  "
            f"{step.wait_slots:>4}  {step.next_ready_slots:>5}  "
            f"{'yes' if step.closes_loop else 'no'}"
        )


def slot_microseconds(rpm: float, slots: int) -> float:
    return 60_000_000.0 / (rpm * slots)


def format_result(label: str, result: RunResult, us_per_slot: float) -> str:
    return (
        f"{label}\n"
        f"  execution: {result.execution_slots:>8} slots "
        f"({result.execution_slots * us_per_slot / 1000:,.3f} ms)\n"
        f"  waiting:   {result.wait_slots:>8} slots "
        f"({result.wait_slots * us_per_slot / 1000:,.3f} ms)\n"
        f"  total:     {result.total_slots:>8} slots "
        f"({result.total_slots * us_per_slot / 1000:,.3f} ms)\n"
        f"  useful-time fraction: {result.utilization:>7.2%}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare consecutive and timing-aware placement on a rotating drum."
    )
    parser.add_argument(
        "--latencies",
        type=parse_latencies,
        default=parse_latencies("3,8,2,5,4,7"),
        help="comma-separated instruction execution times in drum slots",
    )
    parser.add_argument("--slots", type=int, default=50, help="angular slots per revolution")
    parser.add_argument("--rpm", type=float, default=12_500.0, help="drum speed")
    parser.add_argument("--loops", type=int, default=10, help="loop repetitions")
    parser.add_argument(
        "--placement", type=parse_placement,
        help="optional distinct drum slots, in instruction order, for a third layout",
    )
    parser.add_argument(
        "--trace", action="store_true",
        help="show actual execution/wait transitions for every displayed layout",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.slots < 1:
        raise SystemExit("--slots must be positive")
    if args.rpm <= 0:
        raise SystemExit("--rpm must be positive")
    if args.loops < 1:
        raise SystemExit("--loops must be positive")

    latencies = args.latencies
    if args.placement is not None:
        try:
            validate_placement(args.placement, len(latencies), args.slots)
        except ValueError as exc:
            parser.error(str(exc))
    naive = naive_placement(len(latencies), args.slots)
    greedy = greedy_placement(latencies, args.slots)
    us_per_slot = slot_microseconds(args.rpm, args.slots)

    traces: list[tuple[str, TracedRun]] = []

    def evaluate(label: str, placement: list[int]) -> RunResult:
        if args.trace:
            traced = trace_loop(latencies, placement, args.slots, args.loops)
            traces.append((label, traced))
            return traced.result
        return run_loop(latencies, placement, args.slots, args.loops)

    naive_result = evaluate("consecutive", naive)
    greedy_result = evaluate("timing-aware", greedy)

    print(f"drum: {args.rpm:g} rpm, {args.slots} slots/revolution")
    print(f"time per slot: {us_per_slot:.3f} us")
    print(f"instruction latencies: {latencies}")
    print(f"consecutive placement: {naive}")
    print(f"timing-aware placement: {greedy}")
    print()
    print(format_result("consecutive", naive_result, us_per_slot))
    print()
    print(format_result("timing-aware", greedy_result, us_per_slot))

    saved = naive_result.total_slots - greedy_result.total_slots
    print()
    print(
        f"saved by placement in this model: {saved} slots "
        f"({saved * us_per_slot / 1000:,.3f} ms)"
    )

    if args.placement is not None:
        custom_result = evaluate("user placement", args.placement)
        print()
        print(f"user placement: {args.placement}")
        print(format_result("user placement", custom_result, us_per_slot))

    if args.trace or args.placement is not None:
        print()
        print("Synthetic layout experiment, not SOAP or measured IBM 650 instruction timing.")
        print("Each loop includes the closing wait back to its first instruction, even the last loop.")
    for label, traced in traces:
        print()
        print_trace(label, traced)


if __name__ == "__main__":
    main()
