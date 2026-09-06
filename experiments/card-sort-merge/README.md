# Card Sort / Merge Experiment

Historical question:

> Why did sorting punched-card files make comparison, reconciliation, and update processing easier to mechanize?

`card_sort_merge.py` compares two conceptual strategies:

1. repeatedly search an unordered master deck for each transaction;
2. sort both streams by key, then advance through them with a merge-style comparison.

The model assumes one master card per key. A transaction deck may contain
several cards for the same key; after sorting, the merge keeps the matching
master card at the read station until that adjacent transaction group ends.

Run:

```bash
python experiments/card-sort-merge/card_sort_merge.py
```

No third-party dependencies are required.

## What it demonstrates

Once two files are ordered by the same key, matching becomes a local streaming operation. At each step the mechanism needs only compare the current keys and advance one or both streams.

This is the algorithmic property that makes card collators and later tape sort/merge workflows intelligible.

## What it does not reproduce

The script does **not** model:

- IBM 077 mechanics;
- card-feed rates;
- jams;
- sorter passes;
- punch/verify labor;
- physical bins;
- machine setup time;
- exact historical comparison circuitry.

Its comparison counts are pedagogical, not performance measurements.

Historical context: [`../../docs/interaction/why-sorting-cards-was-data-processing.md`](../../docs/interaction/why-sorting-cards-was-data-processing.md).
