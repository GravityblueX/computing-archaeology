# Disk Locality Experiment

Historical question:

> Why can a random-access disk make direct lookup possible while still strongly rewarding locality?

Run:

```bash
python experiments/disk-locality/disk_locality.py
```

The model assigns records to synthetic tracks and charges invented costs for:

- radial seek distance;
- rotational waiting after the seek;
- transfer.

It compares the same selected records in random order and in track-clustered order, plus a sequential run. Output separates seek, rotation, transfer and total time, then traces two consecutive reads of record 0.

## Synthetic timing model

Each workload starts independently at track 0, with record-start angle 0 at the read point. The model uses one ideal spindle and 20 equally spaced record starts per track; all tracks are angularly aligned. Its invented timing constants are 50 ms per revolution, 2.5 ms of seek per track, and 0.15 ms of transfer per record.

Requests execute in the supplied order. There is no cache, host think time, overlapping I/O or controller reordering:

1. Seek to the requested track. The spindle keeps rotating during the seek.
2. Wait for the next occurrence of that record's start angle, measuring the wait **after** seek completion. Arriving exactly at the start needs no rotational wait.
3. Transfer the record. This also advances the spindle before the next request.

The transfer is shorter than the 2.5 ms spacing between record starts; the unused part of that spacing is simply a gap in this toy geometry. These are not measurements of a disk format. Internally, decimal arithmetic keeps these synthetic decimal durations aligned; exposed timings remain floating-point milliseconds.

For example, the first read of record 0 starts immediately and finishes at 0.15 ms. A second read cannot reuse cached data: the next record-0 start arrives at 50 ms, so it waits 49.85 ms and finishes at 50.15 ms. Seeking to the aligned record 0 on the next track also consumes spindle time; it does not reset the angular position.

The callable `run_workload(records)` still returns total milliseconds. `iter_accesses(records)` exposes each record's seek, rotational wait, transfer and cumulative elapsed milliseconds without reordering or modifying the input. An empty workload costs zero, and every new call starts from the same initial state.

This extends the earlier experiment's fixed per-position rotation charge into a continuous synthetic clock. It is an engineering-model enhancement, not a correction to historical RAMAC timing.

## What it demonstrates

Random access removes the requirement to scan every earlier record, but physical positioning still costs time. Reordering work so nearby records are accessed together can reduce head movement dramatically.

Less head movement and less rotational waiting are different effects. The default clustered example has a lower total than its random order, but sorting addresses is not claimed to minimize total access time for every workload.

## What it does not reproduce

This is **not** an IBM 350 simulator. The default timing constants are synthetic and should not be cited as historical RAMAC measurements.

It omits:

- multiple disk surfaces;
- exact IBM actuator geometry;
- real controller rotational scheduling, track skew or sector interleave;
- controller behavior;
- encoding;
- head settling;
- errors and retries;
- queueing.

Historical context: [`../../docs/memory/why-disk-made-random-access-a-business-feature.md`](../../docs/memory/why-disk-made-random-access-a-business-feature.md).
