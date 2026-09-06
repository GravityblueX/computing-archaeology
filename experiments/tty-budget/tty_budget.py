#!/usr/bin/env python3
"""Estimate wall-clock output time for slow serial printing terminals.

Default Model 33 assumptions:
- 110 baud
- 11 signal units per character frame
- therefore about 10 characters per second

This is a bandwidth model, not an electromechanical Teletype emulator.
"""

from __future__ import annotations

import argparse
import math
import time

DEFAULT_EXAMPLES = [
    ("short prompt", 12),
    ("72-column line", 72),
    ("compact error", 24),
    ("500-char help", 500),
    ("1000-char listing", 1000),
    ("80x24 screenful", 80 * 24),
]


def chars_per_second(baud: float, frame_bits: float) -> float:
    if (
        not math.isfinite(baud)
        or not math.isfinite(frame_bits)
        or baud <= 0
        or frame_bits <= 0
    ):
        raise ValueError("baud and frame bits must be positive finite numbers")
    rate = baud / frame_bits
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(
            "baud and frame bits must produce a positive finite character rate"
        )
    return rate


def transmit_seconds(characters: int, baud: float, frame_bits: float) -> float:
    if characters < 0:
        raise ValueError("characters cannot be negative")
    try:
        seconds = characters / chars_per_second(baud, frame_bits)
    except OverflowError as exc:
        raise ValueError(
            "characters and rate must produce a finite transmission duration"
        ) from exc
    if not math.isfinite(seconds):
        raise ValueError(
            "characters and rate must produce a finite transmission duration"
        )
    return seconds


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remainder:04.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {remainder:04.1f}s"


def print_examples(baud: float, frame_bits: float) -> None:
    cps = chars_per_second(baud, frame_bits)
    print(f"baud={baud:g}, frame={frame_bits:g} signal units/character")
    print(f"effective rate: {cps:.3f} characters/second")
    print()
    print("scenario             chars    output time")
    print("-------------------  -------  ----------------")
    for label, count in DEFAULT_EXAMPLES:
        seconds = transmit_seconds(count, baud, frame_bits)
        print(f"{label:<19}  {count:>7}  {format_duration(seconds):>16}")


def live_print(text: str, baud: float, frame_bits: float) -> None:
    delay = 1.0 / chars_per_second(baud, frame_bits)
    for char in text:
        print(char, end="", flush=True)
        time.sleep(delay)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn serial-terminal bandwidth into a user-visible time budget."
    )
    parser.add_argument("--baud", type=float, default=110.0)
    parser.add_argument("--frame-bits", type=float, default=11.0)
    parser.add_argument("--characters", type=int)
    parser.add_argument("--text")
    parser.add_argument(
        "--live",
        action="store_true",
        help="print --text at the modeled character rate (intentionally slow)",
    )
    args = parser.parse_args()

    if not math.isfinite(args.baud) or args.baud <= 0:
        parser.error("--baud must be a positive finite number")
    if not math.isfinite(args.frame_bits) or args.frame_bits <= 0:
        parser.error("--frame-bits must be a positive finite number")
    if args.characters is not None and args.characters < 0:
        parser.error("--characters cannot be negative")
    if args.live and args.text is None:
        parser.error("--live requires --text")

    counts = [count for _, count in DEFAULT_EXAMPLES]
    if args.characters is not None:
        counts.append(args.characters)
    if args.text is not None:
        counts.append(len(args.text))
    try:
        chars_per_second(args.baud, args.frame_bits)
        for count in counts:
            transmit_seconds(count, args.baud, args.frame_bits)
    except ValueError as exc:
        parser.error(str(exc))

    print_examples(args.baud, args.frame_bits)

    if args.characters is not None:
        seconds = transmit_seconds(args.characters, args.baud, args.frame_bits)
        print()
        print(
            f"{args.characters:,} characters -> {format_duration(seconds)} "
            f"at {args.baud:g} baud"
        )

    if args.text is not None:
        seconds = transmit_seconds(len(args.text), args.baud, args.frame_bits)
        print()
        print(
            f"text length {len(args.text)} -> {format_duration(seconds)} "
            f"at {args.baud:g} baud"
        )
        if args.live:
            print("Live modeled output:")
            live_print(args.text, args.baud, args.frame_bits)


if __name__ == "__main__":
    main()
