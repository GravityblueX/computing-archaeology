# Drum timing experiment

This dependency-free Python model accompanies [`docs/memory/why-drum-memory-made-programmers-wait.md`](../../docs/memory/why-drum-memory-made-programmers-wait.md).

## Historical question

If instructions live on a rotating drum, how much performance can be lost when the next instruction is physically in the wrong angular position?

IBM's 1955 IBM 650 brochure specifies a 12,500 rpm drum with 50 word locations per band. Those values are the defaults used here. They imply 4.8 ms per revolution and 96 microseconds per angular location.

## Run

```bash
python experiments/drum-timing/drum_timing.py
```

Try a different sequence of operation times:

```bash
python experiments/drum-timing/drum_timing.py \
  --latencies 2,7,12,3,4 \
  --loops 100
```

Or change the hypothetical drum:

```bash
python experiments/drum-timing/drum_timing.py \
  --slots 100 \
  --rpm 6000
```

## Model

An instruction occupies one angular slot. Its execution latency is expressed as an integer number of drum slots. While the instruction executes, the drum continues rotating.

The program compares two layouts:

1. **consecutive** — instructions are placed in neighboring slots;
2. **timing-aware** — a simple greedy placer tries to put each next instruction at the angular position expected when the previous instruction finishes.

The output separates execution time from rotational waiting time.

With the defaults, consecutive placement is deliberately bad. The example is designed to expose the mechanism, not to reproduce a historically representative IBM 650 program.

## Try your own layout: waiting once can save a revolution

`--placement` adds a third layout. Give one distinct, in-range slot per instruction,
in **instruction order**: `0,2,1` puts instruction 0 at slot 0, instruction 1 at slot
2, and instruction 2 at slot 1. It does not reorder the operations. Unused slots
are allowed, and the first instruction need not be at slot 0.

```bash
python experiments/drum-timing/drum_timing.py \
  --slots 3 --latencies 1,2,2 --loops 1 --placement 0,2,1 --trace
```

This intentionally tiny **synthetic three-slot drum** is not IBM 650 geometry.
The latencies are invented teaching values; compare the integer slots, not a
historical timing inferred from the default rpm.

| Layout | Wait after instruction 0 | Wait after instruction 1 | Closing wait after instruction 2 | Execution / waiting / total slots |
| --- | ---: | ---: | ---: | --- |
| Consecutive and greedy: `0,1,2` | 0 | 2 | 2 | 5 / 4 / **9** |
| User layout: `0,2,1` | 1 | 0 | 0 | 5 / 1 / **6** |

The user layout waits one slot before instruction 1, which starts at time 2.
Instruction 2 can then start immediately at time 4, and the loop is ready again
at time 6. The greedy layout starts instruction 1 earlier, at time 1, but later
waits twice and is not ready again until time 9. An earlier local start is not
necessarily a better whole-loop layout. The existing greedy algorithm is a
heuristic, not a global optimizer; this example does not indicate an arithmetic
bug in it and does not replace it.

### Reading the trace and its measurement boundary

`--trace` works with or without a user layout and observes each displayed run's
actual transitions. It does not run a second simulation to reconstruct the log.
Each row identifies the loop (starting at 1), instruction (starting at 0), its
slot, cumulative start time, execution duration, phase after execution, next
instruction's slot, waiting duration and cumulative next-ready time. Times and
phases are integer slots. `closes-loop: yes` marks the return to instruction 0.

The clock starts with the first instruction already under the head; there is no
initial seek or fetch delay. **Every loop includes its closing wait back to the
first instruction, including the final requested loop.** Thus totals measure
complete cyclic intervals, not a finite job that stops as soon as its last
instruction finishes. In the consecutive example the last instruction finishes
at time 7, then waits 2 slots to close the interval at time 9. No extra instruction
executes during that closing wait. This is the original model's counting rule,
now visible rather than changed.

Without either new option, the original output is unchanged. The four-argument
`run_loop()` API and its two-field `RunResult` are also unchanged. Python callers
can opt into `trace_loop()` for a `TracedRun` containing that same result plus a
tuple of immutable `InstructionStep` observations. Plain `run_loop()` allocates
no instruction snapshots. CLI user layouts are validated before execution;
`validate_placement()` exposes that check for callers. The low-level runners
retain the original model's input assumptions rather than silently adding a new
invalid-input policy to its old API.

Neither manual layout nor trace is SOAP, a historical optimizing result, an IBM
650 instruction-timing emulator or evidence of a designer's intentions. It is a
small experiment in the existing model's cyclic placement constraint.

## What it demonstrates

- a numerical address can also encode physical timing when storage rotates;
- consecutive addresses are not necessarily fast;
- predictable latency can be scheduled around;
- instruction execution time and memory placement can become coupled;
- software tools can optimize physical storage geometry.

## What it does **not** demonstrate

This is **not**:

- an IBM 650 emulator;
- an implementation of SOAP or SOAP II;
- a cycle-accurate model of 650 operations;
- evidence that a historical program used the placements generated here;
- a model of tracks, head selection, branch behavior, I/O, arithmetic overlap, or all timing exceptions.

The experiment tests the engineering mechanism only. Historical claims remain grounded in the IBM brochure, SOAP documentation, and other cited sources in the article.

## Reference values

- IBM, *650 Magnetic Drum Data Processing Machine*, 1955: https://s3data.computerhistory.org/brochures/ibm.650.1955.102646125.pdf
- IBM, *Reference Manual: SOAP II for the IBM 650 Data Processing System*, 1957: https://www.bitsavers.org/pdf/ibm/650/24-4000-0_SOAPII.pdf
