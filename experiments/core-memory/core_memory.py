#!/usr/bin/env python3
"""Small conceptual model of coincident-current magnetic core memory.

This program exposes selection geometry and destructive read/restore behavior.
It does not numerically simulate ferrite hysteresis, currents, timing, or noise.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Literal


ReadPhase = Literal["SELECT", "READ_CLEAR", "RESTORE_WRITE", "RESTORE_SKIP", "COMPLETE"]
RestoreAction = Literal["pending", "write-one", "disabled", "already-zero"]


@dataclass(frozen=True)
class ReadStep:
    """Copied state at a conceptual read stage, not a measured hardware phase."""

    phase: ReadPhase
    row: int
    col: int
    bits: tuple[tuple[int, ...], ...]
    observed_bit: int | None
    sense_pulse: bool | None
    restore_action: RestoreAction

    @property
    def core_bit(self) -> int:
        return self.bits[self.row][self.col]


@dataclass
class ReadResult:
    row: int
    col: int
    observed_bit: int
    sense_pulse: bool
    restored: bool
    trace: tuple[ReadStep, ...] = ()


class CorePlane:
    def __init__(self, size: int = 4) -> None:
        if size < 2:
            raise ValueError("size must be at least 2")
        self.size = size
        self.bits = [[0 for _ in range(size)] for _ in range(size)]

    def _check(self, row: int, col: int) -> None:
        if not (0 <= row < self.size and 0 <= col < self.size):
            raise IndexError("row/col outside plane")

    def seed_checkerboard(self) -> None:
        for row in range(self.size):
            for col in range(self.size):
                self.bits[row][col] = (row + col) % 2

    def write(self, row: int, col: int, value: int) -> None:
        self._check(row, col)
        if value not in (0, 1):
            raise ValueError("core value must be 0 or 1")
        self.bits[row][col] = value

    def selection_map(self, row: int, col: int) -> list[list[float]]:
        """Return normalized excitation: 1.0 target, 0.5 half-selected, 0 elsewhere."""
        self._check(row, col)
        result: list[list[float]] = []
        for r in range(self.size):
            line: list[float] = []
            for c in range(self.size):
                excitation = 0.0
                if r == row:
                    excitation += 0.5
                if c == col:
                    excitation += 0.5
                line.append(excitation)
            result.append(line)
        return result

    def destructive_read(
        self, row: int, col: int, restore: bool = True, *, trace: bool = False
    ) -> ReadResult:
        """Force a bit to 0; optionally retain snapshots of this same read cycle.

        Clearing and sensing form one conceptual stage. The stored bit can be
        zero while the recovered logical value is one; restoration uses the
        recovered value, not a second read of the now-cleared core.
        """
        self._check(row, col)
        steps: list[ReadStep] | None = [] if trace else None

        def record(
            phase: ReadPhase,
            observed: int | None,
            sensed: bool | None,
            action: RestoreAction,
        ) -> None:
            if steps is not None:
                steps.append(ReadStep(
                    phase=phase,
                    row=row,
                    col=col,
                    bits=tuple(tuple(line) for line in self.bits),
                    observed_bit=observed,
                    sense_pulse=sensed,
                    restore_action=action,
                ))

        record("SELECT", None, None, "pending")
        old = self.bits[row][col]
        sense_pulse = old == 1

        # Conceptual read: forcing the target toward zero destroys a stored one.
        self.bits[row][col] = 0
        record("READ_CLEAR", old, sense_pulse, "pending")

        restored = False
        restore_action: RestoreAction
        if restore and old == 1:
            self.bits[row][col] = 1
            restored = True
            restore_action = "write-one"
            record("RESTORE_WRITE", old, sense_pulse, restore_action)
        else:
            restore_action = "already-zero" if restore else "disabled"
            record("RESTORE_SKIP", old, sense_pulse, restore_action)

        record("COMPLETE", old, sense_pulse, restore_action)

        return ReadResult(
            row=row,
            col=col,
            observed_bit=old,
            sense_pulse=sense_pulse,
            restored=restored,
            trace=tuple(steps) if steps is not None else (),
        )

    def render(self) -> str:
        return "\n".join(" ".join(str(bit) for bit in row) for row in self.bits)


def render_selection(selection: list[list[float]]) -> str:
    return "\n".join(" ".join(f"{value:.1f}" for value in row) for row in selection)


def render_read_trace(trace: tuple[ReadStep, ...]) -> str:
    lines = ["Conceptual read trace (snapshots, not measured timing)"]
    for index, step in enumerate(trace, 1):
        observed = "?" if step.observed_bit is None else str(step.observed_bit)
        sensed = "?" if step.sense_pulse is None else str(step.sense_pulse)
        lines.append(
            f"{index}. {step.phase} selected={step.core_bit} "
            f"observed={observed} sense={sensed} restore={step.restore_action}"
        )
        lines.extend(" ".join(str(bit) for bit in row) for row in step.bits)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demonstrate coincident selection and destructive core-memory reads."
    )
    parser.add_argument("--size", type=int, default=4)
    parser.add_argument("--row", type=int, default=1)
    parser.add_argument("--col", type=int, default=2)
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="leave a destructive read cleared instead of restoring a stored 1",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="show conceptual read/clear/restore snapshots, not physical timing",
    )
    args = parser.parse_args()

    plane = CorePlane(args.size)
    plane.seed_checkerboard()
    plane._check(args.row, args.col)

    print("Initial conceptual core plane")
    print(plane.render())
    print()

    print(f"Normalized selection for row={args.row}, col={args.col}")
    print("0.5 = half-selected; 1.0 = selected intersection")
    print(render_selection(plane.selection_map(args.row, args.col)))
    print()

    before = plane.bits[args.row][args.col]
    result = plane.destructive_read(
        args.row, args.col, restore=not args.no_restore, trace=args.trace
    )

    print(f"Bit before read: {before}")
    print(f"Sense pulse observed: {result.sense_pulse}")
    print(f"Recovered logical value: {result.observed_bit}")
    print(f"Restored after read: {result.restored}")
    print()

    if args.trace:
        print(render_read_trace(result.trace))
        print()

    print("Plane after read sequence")
    print(plane.render())

    if args.no_restore and before == 1:
        print()
        print("The selected 1 is now lost: destructive read was left unrestored.")


if __name__ == "__main__":
    main()
