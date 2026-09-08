# Flash erase granularity

## Historical question

What system work appears when a nonvolatile array can program small units but must erase a larger group before those cells can be reused?

## Run

```bash
python experiments/flash-erase/flash_erase.py
```

## Original single-hotspot model

A deterministic synthetic array has eight blocks of eight pages. One hundred twenty-eight updates target one logical page. The `in_place` strategy erases the containing block on every update. The `append_reclaim` strategy writes successive versions into free physical pages and only reclaims a block after cycling through the available array.

The original functions and comparison remain unchanged: the default append case
uses 128 page programs and eight erases. When that single-hotspot workload returns
to an old block, its pages are stale; there are no other live logical pages there
to preserve. This is a declared simplification, not a model of arbitrary updates.

## One supplied-victim relocation

The default command now also asks: **why does erasing an eight-page block not
necessarily give the device eight more free pages?**

This separate, small example represents three blocks: a fully programmed victim,
a block holding replacement versions, and an erased scratch block. A stored page
has a logical ID and a string value. A latest-version map identifies the physical
page that currently supplies each logical value; older copies can still contain
data without being live.

`reclaim_block` takes this state, one specified victim and an ordered list of
already-erased destination pages outside it. It checks that the map names actual
stored logical pages and that enough distinct erased destinations exist. It then:

1. reads each live page's actual ID/value;
2. programs a supplied erased destination page with that value;
3. moves that logical ID's mapping to the destination;
4. erases the victim only after all live pages have been preserved.

Inputs are unchanged; the result contains a separate read-only page/map snapshot
and an operation trace. No destination is created by prematurely erasing the
victim. Extra supplied destinations remain unused. This is a single relocation
event, not a victim-selection or garbage-collection scheduling policy.

The default comparison uses the same invented eight-page geometry:

| Victim contents | GC reads | Copy programs | Erases | Net free-page gain |
|---|---:|---:|---:|---:|
| eight stale pages | 0 | 0 | 1 | 8 |
| six live, two stale pages | 6 | 6 | 1 | 2 |

Copying six live pages consumes six existing free pages before erasure releases
eight. The experiment counts free pages across the whole device before and after;
the net gain is therefore two, not eight. A forced relocation of an all-live block
copies every page but creates **no net free capacity**. That boundary is not a
recommendation that a collector choose an all-live victim.

The four-page trace makes value preservation visible. The victim holds original
L0..L3; newer L0/L1 are already at p4/p5. Only p2 and p3 remain live, so they move to
p8 and p9, mappings move with them, and finally p0..p3 are erased. L0/L1 remain
`updated`, L2/L3 remain `original`, and free pages go from six to eight. Copying old
L0/L1 versions back into the latest map would be data loss, not reclamation.

### Evidence and reconstruction boundary

The read-live / rewrite-live / erase sequence and latest-map test are explained
in Remzi H. Arpaci-Dusseau and Andrea C. Arpaci-Dusseau,
[*Operating Systems: Three Easy Pieces*, version 1.10, chapter 44,
“Flash-based SSDs,” §44.8, pp. 10–11](https://pages.cs.wisc.edu/~remzi/OSTEP/file-ssd.pdf).
This publicly available scholarly technical explanation supports the generic
mechanism, not a priority claim or a specific manufacturer's historical policy.

The block sizes, values, victim choice and available scratch space here are
**synthetic engineering assumptions**, not historical measurements. Under those
assumptions, a B-page victim with L live pages needs L read/program relocations
and gains B−L free pages. The program exposes actual page transitions and counts,
not a steady-state SSD write-amplification or endurance prediction.

For the existing historical context, see
[`why-read-only-memory-kept-changing.md`](../../docs/memory/why-read-only-memory-kept-changing.md).

## What it demonstrates

- small logical updates need not map to equally small physical erases;
- out-of-place updates can postpone erase work;
- erase placement changes how concentrated wear becomes;
- hiding erase granularity requires mapping state and reclamation policy below a block interface.
- preserving live values requires hidden reads and programs before block reuse;
- a whole-block erase can produce much less net free capacity than its block size.

## What it cannot establish

This is not a NAND command-set emulator, full flash-translation layer, endurance
predictor, or performance benchmark. The added example accounts for live/stale
versions and copying in **one supplied block event**, but does not simulate a GC
trigger, victim-selection policy, continued host-write workload, TRIM, global
wear management, bad blocks, ECC, retention, program/erase timing, overprovisioning
policy, or power-loss recovery. Operations are serial and fault-free. The supplied
scratch space is not a performance claim about a real device's spare capacity.
Its geometry and counts are invented to make these constraints visible.
