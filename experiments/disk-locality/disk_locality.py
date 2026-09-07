"""Synthetic moving-head disk timing; not an IBM 350 simulator."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from math import fsum
import random

TRACKS = 200
RECORDS_PER_TRACK = 20
SEEK_PER_TRACK_MS = 2.5  # synthetic
FULL_ROTATION_MS = 50.0  # synthetic
TRANSFER_PER_RECORD_MS = 0.15  # synthetic


@dataclass(frozen=True)
class AccessTiming:
    record: int
    seek_ms: float
    rotation_ms: float
    transfer_ms: float
    elapsed_ms: float


def iter_accesses(records: Iterable[int]) -> Iterator[AccessTiming]:
    """Read in supplied order, starting at track 0 and record-start angle 0."""
    # Exact decimal toy durations avoid rounding an on-time arrival into an
    # additional revolution. Public timings remain milliseconds as floats.
    revolution = Decimal(str(FULL_ROTATION_MS))
    seek_per_track = Decimal(str(SEEK_PER_TRACK_MS))
    transfer = Decimal(str(TRANSFER_PER_RECORD_MS))
    record_pitch = revolution / RECORDS_PER_TRACK
    previous_track = 0
    elapsed = Decimal(0)
    for record in records:
        track, offset = divmod(record, RECORDS_PER_TRACK)
        seek = abs(track - previous_track) * seek_per_track
        elapsed += seek
        phase = elapsed % revolution
        target = offset * record_pitch
        # Decimal's remainder retains the sign; add one revolution before
        # wrapping the difference so a just-missed record waits for its return.
        rotation = (target - phase + revolution) % revolution
        elapsed += rotation + transfer
        previous_track = track
        yield AccessTiming(
            record, float(seek), float(rotation), float(transfer), float(elapsed)
        )


def run_workload(records):
    """Return total milliseconds, preserving the original simple interface."""
    elapsed = 0.0
    for access in iter_accesses(records):
        elapsed = access.elapsed_ms
    return elapsed


def main():
    random.seed(305)
    sample = random.sample(range(TRACKS * RECORDS_PER_TRACK), 80)
    random_order = sample[:]
    clustered_order = sorted(sample)

    sequential = list(range(1000, 1080))

    print("Synthetic moving-head disk locality model")
    print(f"records requested per workload: {len(sample)}")
    print("Each workload starts at track 0, record-start angle 0.")
    print(
        f"{'workload':24s} {'seek':>10s} {'rotation':>10s} {'transfer':>10s} {'total':>10s} (ms)"
    )
    for label, records in [
        ("random-order", random_order),
        ("same records, clustered", clustered_order),
        ("sequential run", sequential),
    ]:
        trace = list(iter_accesses(records))
        print(
            f"{label:24s} {fsum(a.seek_ms for a in trace):10.2f} "
            f"{fsum(a.rotation_ms for a in trace):10.2f} "
            f"{fsum(a.transfer_ms for a in trace):10.2f} {trace[-1].elapsed_ms:10.2f}"
        )
    print()
    print("Repeated record, no cache: [0, 0]")
    print("read  record    seek  rotation  transfer  elapsed (ms)")
    for index, access in enumerate(iter_accesses([0, 0]), start=1):
        print(
            f"{index:4d} {access.record:7d} {access.seek_ms:7.2f} "
            f"{access.rotation_ms:9.2f} {access.transfer_ms:9.2f} {access.elapsed_ms:8.2f}"
        )
    print("The second read waits for the same record start to return.")
    print()
    print("All timing constants are invented teaching parameters.")
    print("The experiment demonstrates geometry/locality, not IBM 350 timing.")


if __name__ == "__main__":
    main()
