#!/usr/bin/env python3
"""Synthetic Flash erase-granularity and wear-distribution model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

PAGES_PER_BLOCK = 8
BLOCKS = 8
UPDATES = 128


def naive_updates(updates: int = UPDATES) -> list[int]:
    """Rewrite one logical page in place, erasing its block for every update."""
    erase_counts = [0] * BLOCKS
    for _ in range(updates):
        erase_counts[0] += 1
    return erase_counts


def log_structured_updates(updates: int = UPDATES) -> tuple[list[int], int]:
    """Append versions and reclaim full blocks in round-robin order."""
    erase_counts = [0] * BLOCKS
    physical_page = 0
    for _ in range(updates):
        block = (physical_page // PAGES_PER_BLOCK) % BLOCKS
        offset = physical_page % PAGES_PER_BLOCK
        if offset == 0 and physical_page >= PAGES_PER_BLOCK * BLOCKS:
            erase_counts[block] += 1
        physical_page += 1
    return erase_counts, physical_page


def spread(counts: list[int]) -> int:
    return max(counts) - min(counts)


@dataclass(frozen=True)
class FlashPage:
    logical_id: str
    value: str


@dataclass(frozen=True)
class Operation:
    action: str
    logical_id: str | None = None
    value: str | None = None
    source: int | None = None
    destination: int | None = None
    block: int | None = None


@dataclass(frozen=True)
class ReclaimResult:
    pages: tuple[FlashPage | None, ...]
    latest: Mapping[str, int]
    operations: tuple[Operation, ...]
    free_before: int
    free_after: int

    @property
    def gc_reads(self) -> int:
        return sum(op.action == "read" for op in self.operations)

    @property
    def copy_programs(self) -> int:
        return sum(op.action == "program" for op in self.operations)

    @property
    def erases(self) -> int:
        return sum(op.action == "erase" for op in self.operations)

    @property
    def net_free_gain(self) -> int:
        return self.free_after - self.free_before


def reclaim_block(
    pages: Sequence[FlashPage | None],
    latest: Mapping[str, int],
    *,
    victim_block: int,
    destination_pages: Sequence[int],
    pages_per_block: int = PAGES_PER_BLOCK,
) -> ReclaimResult:
    """Relocate one supplied, fully programmed block; leave input state untouched.

    None denotes an erased physical page. The latest map, not the mere presence
    of data, determines liveness. Destinations are supplied erased pages outside
    the victim, used in the supplied order. This is one event, not a GC policy.
    """
    if pages_per_block < 1 or len(pages) % pages_per_block:
        raise ValueError("the array must contain whole, nonempty blocks")
    start = victim_block * pages_per_block
    stop = start + pages_per_block
    if start < 0 or stop > len(pages):
        raise ValueError("victim block is outside the array")
    victim = range(start, stop)
    if any(pages[position] is None for position in victim):
        raise ValueError("this demonstration requires a fully programmed victim")
    for logical_id, position in latest.items():
        if not 0 <= position < len(pages):
            raise ValueError("latest mapping is outside the array")
        page = pages[position]
        if page is None or page.logical_id != logical_id:
            raise ValueError("latest mapping must name its stored logical page")

    live: list[tuple[int, FlashPage]] = []
    for position in victim:
        page = pages[position]
        if page is not None and latest.get(page.logical_id) == position:
            live.append((position, page))
    destinations = tuple(destination_pages)
    if len(set(destinations)) != len(destinations):
        raise ValueError("destination pages must be distinct")
    for position in destinations:
        if not 0 <= position < len(pages) or position in victim:
            raise ValueError("destinations must be outside the victim within the array")
        if pages[position] is not None:
            raise ValueError("destinations must already be erased")
    if len(destinations) < len(live):
        raise ValueError("not enough erased destination pages to preserve live data")

    cells = list(pages)
    current = dict(latest)
    free_before = cells.count(None)
    operations: list[Operation] = []
    for (source, page), destination in zip(live, destinations):
        # Save the actual live value before any victim page is erased.
        saved = cells[source]
        assert saved is not None
        operations.append(
            Operation("read", saved.logical_id, saved.value, source=source)
        )
        cells[destination] = saved
        operations.append(
            Operation("program", saved.logical_id, saved.value, destination=destination)
        )
        current[page.logical_id] = destination
        operations.append(
            Operation("remap", page.logical_id, source=source, destination=destination)
        )

    # All latest references to the victim have moved before the block erase.
    for position in victim:
        cells[position] = None
    operations.append(Operation("erase", block=victim_block))
    return ReclaimResult(
        pages=tuple(cells),
        latest=MappingProxyType(current),
        operations=tuple(operations),
        free_before=free_before,
        free_after=cells.count(None),
    )


def _demo_state(
    block_pages: int, live_pages: int
) -> tuple[list[FlashPage | None], dict[str, int], list[int]]:
    """Invented victim, replacement-version block and erased scratch block."""
    pages: list[FlashPage | None] = [None] * (3 * block_pages)
    latest = {}
    for offset in range(block_pages):
        logical_id = f"L{offset}"
        pages[offset] = FlashPage(logical_id, "original")
        latest[logical_id] = offset
        if offset < block_pages - live_pages:
            pages[block_pages + offset] = FlashPage(logical_id, "updated")
            latest[logical_id] = block_pages + offset
    return pages, latest, list(range(2 * block_pages, 3 * block_pages))


def _values(pages: Sequence[FlashPage | None], latest: Mapping[str, int]) -> str:
    values = []
    for key, position in latest.items():
        page = pages[position]
        assert page is not None
        values.append(f"{key}={page.value}")
    return " ".join(values)


def show_relocation_examples() -> None:
    print("\nOne supplied-victim relocation: synthetic pages and values")
    for name, live_count in (("all_stale", 0), ("mixed_live", 6)):
        pages, latest, destinations = _demo_state(8, live_count)
        result = reclaim_block(
            pages, latest, victim_block=0, destination_pages=destinations
        )
        print(
            f"scenario={name} block_pages=8 live={result.gc_reads} "
            f"gc_reads={result.gc_reads} copy_programs={result.copy_programs} "
            f"erases={result.erases} free_pages={result.free_before}->{result.free_after} "
            f"net_free_gain={result.net_free_gain}"
        )

    pages, latest, destinations = _demo_state(4, 2)
    result = reclaim_block(
        pages, latest, victim_block=0, destination_pages=destinations, pages_per_block=4
    )
    print("\nFour-page identity trace (three blocks; p8..p11 start erased)")
    for position in range(4):
        page = pages[position]
        assert page is not None
        status = "live" if latest[page.logical_id] == position else "stale"
        print(f"victim p{position}: {page.logical_id}={page.value} {status}")
    print("values before:", _values(pages, latest))
    for op in result.operations:
        if op.action == "read":
            print(f"READ p{op.source} {op.logical_id}={op.value}")
        elif op.action == "program":
            print(f"PROGRAM p{op.destination} {op.logical_id}={op.value}")
        elif op.action == "remap":
            print(f"REMAP {op.logical_id} p{op.source}->p{op.destination}")
        else:
            print(f"ERASE block={op.block} pages=p0..p3")
    print("values after: ", _values(result.pages, result.latest))
    print(
        f"free_pages={result.free_before}->{result.free_after} net_free_gain={result.net_free_gain}"
    )
    print("Copies consume existing free pages before erase frees the victim.")
    print(
        "No GC selection policy, device timing, endurance, or steady-state amplification is modeled."
    )


def main() -> None:
    naive = naive_updates()
    log_counts, physical_writes = log_structured_updates()
    print(f"geometry={BLOCKS}_blocks x {PAGES_PER_BLOCK}_pages updates={UPDATES}")
    print(
        f"strategy=in_place       erases={sum(naive):2d} max_block_erases={max(naive):2d} spread={spread(naive):2d}"
    )
    print(
        f"strategy=append_reclaim erases={sum(log_counts):2d} max_block_erases={max(log_counts):2d} "
        f"spread={spread(log_counts):2d} physical_writes={physical_writes}"
    )
    print(
        "Counts are synthetic. The model exposes erase-before-reuse and wear placement, not NAND firmware."
    )
    show_relocation_examples()


if __name__ == "__main__":
    main()
