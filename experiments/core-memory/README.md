# Core Memory Experiment

Historical question:

> How can two shared coordinate wires select one magnetic bit, and why does a destructive read require restoration?

This is a **conceptual control-sequence model**, not a magnetic-field simulator or a faithful Whirlwind emulator.

## What it demonstrates

The script builds a small bit plane and exposes four ideas.

### 1. Half selection

Selecting one row gives every core on that row a normalized excitation of `0.5`.

Selecting one column does the same for that column.

### 2. Coincidence

At the selected row/column intersection, the two contributions add:

```text
0.5 + 0.5 = 1.0
```

The model treats `1.0` as the conceptual switching threshold.

This illustrates the addressing idea in Jay Forrester's coincident-current work: shared coordinate lines can select one element because the material responds differently to partial and coincident excitation.

### 3. Destructive read and restore

The model reads a bit by forcing it to zero.

If the old value was one, a conceptual sense pulse occurs because the state changed. The model can then restore the original one.

Run with `--no-restore` to leave the read bit destroyed.

### 4. Seeing the read cycle, not just its endpoints

Add `--trace` to inspect copied plane states from the **same** read operation.
For the default selected one, the stage summaries are:

```text
1. SELECT selected=1 observed=? sense=? restore=pending
2. READ_CLEAR selected=0 observed=1 sense=True restore=pending
3. RESTORE_WRITE selected=1 observed=1 sense=True restore=write-one
4. COMPLETE selected=1 observed=1 sense=True restore=write-one
```

Each summary is followed by its complete plane snapshot. At `READ_CLEAR`, the
selected core is already zero, but the recovered logical value is still one.
Writing that retained value back is what preserves the data. This distinction
is hidden if we compare only the initial and final planes, both of which hold
one at the selected location.

With `--trace --no-restore`, stages 3 and 4 instead show:

```text
3. RESTORE_SKIP selected=0 observed=1 sense=True restore=disabled
4. COMPLETE selected=0 observed=1 sense=True restore=disabled
```

A second read would now recover zero with no sense pulse. For an initially zero
core, `--trace --row 0 --col 0` shows:

```text
2. READ_CLEAR selected=0 observed=0 sense=False restore=pending
3. RESTORE_SKIP selected=0 observed=0 sense=False restore=already-zero
4. COMPLETE selected=0 observed=0 sense=False restore=already-zero
```

`already-zero` means no write of one was necessary, not that recovery failed.
`disabled` records the caller's no-restore policy, including when the core was
already zero. `?` at selection means sensing has not yet occurred in this model.
The old `ReadResult.restored` field continues to mean that a one was written
back, not merely that restoration was requested.

The 1981 *Memory Technology Survey* describes coincident half-selection on
printed p. A-10 and reads that clear the core, sense its old value, and require
rewriting for retention on p. A-11.[^nasa-core] It is a later technical survey,
not a record of every 1950s machine's control timing. Our stage names and
snapshots are pedagogical: `READ_CLEAR` deliberately groups clearing and
sensing, and the separate `COMPLETE` record is an observation boundary, not an
additional physical operation or clock phase.

For Python callers, `destructive_read(row, col, restore=True)` keeps its old
positional arguments and five result fields. The optional keyword-only
`trace=True` adds a tuple in `result.trace`; each frozen `ReadStep` stores a
tuple-of-tuples plane copy at that stage. Later writes or reads cannot change
these snapshots. Without the flag, `result.trace` is empty and no plane
snapshots are copied; existing default CLI output is unchanged.

## Run

```bash
python experiments/core-memory/core_memory.py
```

Try another address:

```bash
python experiments/core-memory/core_memory.py --size 8 --row 5 --col 3
```

Show the consequence of skipping restore:

```bash
python experiments/core-memory/core_memory.py --row 1 --col 2 --no-restore
```

Inspect restoration and compare it with a zero bit:

```bash
python experiments/core-memory/core_memory.py --trace
python experiments/core-memory/core_memory.py --trace --no-restore
python experiments/core-memory/core_memory.py --trace --row 0 --col 0
```

No third-party dependencies are required.

## What this does **not** model

It does not numerically reproduce:

- a ferrite hysteresis curve;
- actual switching current;
- pulse width;
- sense-amplifier voltage;
- inhibit-wire schemes;
- temperature effects;
- half-select disturbance;
- noise margins;
- word-oriented plane stacking;
- historical core sizes;
- Whirlwind timing;
- manufacturing defects.

The normalized `0.5` and `1.0` values are pedagogical labels, not measured amperes.

## Source anchors

- Jay W. Forrester, “Digital Information Storage in Three Dimensions Using Magnetic Cores,” *Journal of Applied Physics* 22(1), 1951, pp. 44–48.
- Jay W. Forrester, U.S. Patent 2,736,880, filed 1951.
- Smithsonian Whirlwind magnetic-core plane object record.
- Computer History Museum, magnetic-core memory and Storage Engine exhibits.

The companion article is:

[`../../docs/memory/why-core-memory-was-worth-weaving.md`](../../docs/memory/why-core-memory-was-worth-weaving.md)

## Interpretation rule

The experiment demonstrates why the **control sequence** is coherent. It does not establish who invented every component of core memory, the exact behavior of every historical array, or the economics of any particular installation.

[^nasa-core]: McDonnell Douglas Astronautics Company, *Memory Technology Survey*, Report MDC E2365 / NASA-CR-170450, 13 February 1981, printed pp. A-10–A-11 (PDF pp. 61–62), “Magnetic Memories / Cores.” [NASA NTRS record](https://ntrs.nasa.gov/citations/19830006682); [report, p. A-11](https://ntrs.nasa.gov/api/citations/19830006682/downloads/19830006682.pdf#page=62).
