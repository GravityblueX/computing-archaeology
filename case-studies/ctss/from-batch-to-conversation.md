# CTSS: From Batch Queue to Conversation

Batch processing solved a real economic problem: expensive computers should not sit idle while humans mount tapes, sort cards, correct syntax, or think about what to do next.

Then time-sharing appeared to do something that sounds like the opposite.

It deliberately put humans back into a live interaction loop with a large computer.

That does **not** mean batch processing had been a mistake.

It means the constraint equation changed.

The Compatible Time-Sharing System (CTSS) at MIT is a particularly useful case because its surviving documentation explains both the user goal and the machinery required to make that goal safe enough to operate.

The historical question is:

> **What had to become true before an expensive mainframe could feel like many personal conversational machines at once?**

## Time-sharing was about a different kind of efficiency

The 1966 edition of the *CTSS Programmer's Guide* begins by noting that the term *time-sharing* could mean several things.

It distinguishes ordinary multiprogramming aimed at efficient hardware utilization from the CTSS goal: **concurrent, effective utilization of one computer by several users**.[^ctss-guide]

The manual identifies the motivation as the poor rate of interaction between people and large computers.[^ctss-guide]

That distinction matters.

Batch systems optimize something like:

```text
How do we keep the expensive machine busy?
```

Interactive time-sharing adds another question:

```text
How do we keep the human's problem-solving loop moving?
```

Those objectives can conflict.

A system may achieve excellent processor utilization while making a programmer wait hours for a one-character correction.

CTSS treated that delay as a problem worth spending hardware and software complexity to reduce.

## The 1962 experimental system

Fernando Corbató, Marjorie Merwin-Daggett, Robert Daley, and colleagues presented an experimental time-sharing system for the IBM 7090 in 1962.[^ctss-paper]

The paper's stated purpose included the need for time-sharing, implementation problems, the experimental system, and scheduling.[^ctss-paper]

This should not be turned into an unqualified slogan that CTSS was simply 'the first time-sharing system.' Multiple projects explored overlapping ideas, and priority depends on what counts as an operating system, a demonstration, simultaneous use, remote use, or production service.

CTSS is important enough without turning the history into a trophy contest.

Its value here is that it makes the constraint transition unusually visible.

## A fast CPU and a slow human can share well

A human interactive session is extremely bursty.

The user may:

1. type a short command;
2. demand a burst of computation;
3. read the answer;
4. think;
5. edit something;
6. pause again.

The CPU is not needed during much of that human time.

A printing terminal might deliver only around ten characters per second. A person may then spend seconds or minutes deciding what to do with the result.

If the machine is reserved for one user during all of that thinking, most of the computational resource is wasted.

Time-sharing exploits the mismatch:

```text
human timescale:      seconds
terminal timescale:   tenths of seconds per character
CPU timescale:        far shorter computational events
```

While one person reads, someone else's program can run.

While another person types, a third user's request can be serviced.

The system works economically when these bursts are sufficiently interleaved that users perceive useful responsiveness without all demanding full CPU capacity simultaneously.

This is statistical multiplexing applied to human attention.

## But the illusion requires forced interruption

Suppose user A enters an infinite loop.

Without a way to regain control, the operating system cannot politely ask the program to stop and give user B a turn.

CTSS therefore needed hardware that could interrupt computation after an interval.

The *CTSS Technical Notes* describe an IBM 7094 with a **core-storage interval timer clock** capable of causing a program interruption.[^ctss-tech]

This is a fundamental time-sharing primitive.

The operating system needs a source of authority stronger than the running user program.

Conceptually:

```text
run user program
-> timer expires
-> trap to supervisor
-> account for time
-> decide what runs next
```

Without preemption, one bad or merely long-running program can destroy the shared interactive service.

## Memory protection is not optional politeness

Now suppose user A accidentally writes into user B's memory.

Or worse, overwrites the operating-system supervisor.

A shared machine cannot rely on every program behaving perfectly.

The CTSS hardware modifications included **memory protection and relocation registers**. The technical notes explain that protected regions and instructions could be declared off-limits and that violations caused traps.[^ctss-tech]

This is another moment where architecture and social organization become the same thing.

Multiple independent users can coexist only if the hardware helps enforce boundaries between them.

A memory-protection register is therefore not merely a clever circuit.

It is part of the institutional claim:

> strangers can safely share one expensive computer.

## Relocation helps make 'my memory' an abstraction

If every user's program had to be compiled for one fixed physical memory range, moving programs in and out of memory would be awkward.

Relocation lets an address used by a program be interpreted relative to where the program is actually loaded.

That matters because time-sharing systems must constantly manage scarce fast memory among many competing programs.

The user wants to think:

```text
my program starts here
```

while the machine wants the freedom to decide:

```text
this user's current image lives in these physical words right now
```

This gap between **logical view** and **physical placement** becomes one of the defining abstractions of operating systems.

## Secondary storage makes memory into a moving frontier

Core memory was expensive.

A time-sharing system cannot necessarily keep every user's complete working set resident at once.

CTSS therefore depended on disk and drum storage as part of the active system architecture. The technical notes list disk and drum storage channels and discuss the relationship between users, supervisor, and secondary storage.[^ctss-tech]

This changes what 'memory' means operationally.

A user's session can persist even while parts of it are not in core.

The operating system moves information between:

```text
fast scarce memory
<->
slower larger storage
```

in order to preserve the illusion of many simultaneously available computational contexts.

Time-sharing is therefore partly a **memory traffic problem**.

## The terminal is remote from the user process

CTSS terminal input did not travel straight from keyboard to the currently running program.

The technical notes describe a path in which a typed character travels by telephone line to an IBM 7750 communications computer, then through an I/O channel into the 7094, where supervisor code buffers it and associates it with the correct user.[^ctss-tech]

The user's program may not even be in core memory at that exact instant.

So the supervisor must buffer input independently of process residency.

This is a major conceptual shift.

Input becomes an event belonging to a **logical session**, not merely an electrical signal consumed immediately by whatever code happens to be executing.

## One keystroke requires operating-system machinery

The path of a single character can be read as a miniature architecture diagram:

```text
keyboard
-> teleprinter encoder
-> telephone circuit
-> communications equipment
-> communications computer
-> channel hardware
-> supervisor interrupt
-> shared buffer
-> logical user mapping
-> user-level message
```

Each layer exists because the next layer runs on a different timescale or has different responsibilities.

The human does not need to know this.

That invisibility is the achievement.

## Why buffering is essential

A printing terminal does not stop producing physical events merely because the user's process has been swapped out.

Similarly, the main CPU should not have to wait synchronously for each slow character to finish printing.

CTSS used buffers on both input and output paths. The technical notes describe supervisor input buffers and output storage in the 7750 communications computer.[^ctss-tech]

Buffering decouples timescales.

This principle recurs everywhere in computing:

```text
fast producer + slow consumer -> buffer
slow producer + fast consumer -> buffer
bursty producer + scheduled consumer -> buffer
```

The terminal subsystem is therefore not peripheral to time-sharing architecture.

It is one of the places where time-sharing becomes physically possible.

## Scheduling becomes a user-experience mechanism

A batch scheduler can optimize throughput without caring whether one individual job gets a response in 0.5 seconds or 50 seconds.

An interactive scheduler cannot.

The system must repeatedly decide:

- who runs next;
- how long they run;
- whether an I/O-bound user should remain blocked;
- whether a compute-heavy job should be preempted;
- how to prevent one user from monopolizing service;
- how much context-switch overhead is acceptable;
- what response delay humans will notice.

Scheduling policy therefore becomes part of the interface.

The user never sees the queue directly, but feels it as responsiveness.

## 'Personal' computing before personal hardware

Time-sharing creates an important historical inversion.

A user can experience:

- a private login;
- personal files;
- an interactive command environment;
- editors;
- programming languages;
- persistent work;
- remote access;

without owning a computer.

The physical machine remains centralized and shared.

The **experience** becomes increasingly individual.

This is why the history of personal computing cannot be reduced to the moment a small computer appears on a desk.

Some of the social and interface expectations of personal computing were rehearsed on large shared machines first.

## Interactive editing changes programming practice

In a batch workflow, a small source correction may require:

```text
edit physical deck
-> submit
-> wait in queue
-> compile
-> run
-> inspect output later
```

In time-sharing, the loop becomes closer to:

```text
edit line
-> compile/run
-> see result
-> edit again
```

Even if the CPU itself is not fundamentally different, the **iteration latency** is.

That changes which mistakes are cheap, how people explore programs, how documentation can be consulted, and how software can be developed experimentally.

A computing environment with short feedback encourages different habits from one where every run is an appointment with a batch queue.

## CTSS did not eliminate batch

The phrase *Compatible Time-Sharing System* matters.

The project was designed to coexist with more conventional use of the machine rather than assume that all computation should instantly become interactive.

The CTSS manual explicitly discusses the compatibility of time-sharing with background operation.[^ctss-guide]

That is historically sensible.

Some workloads are naturally interactive:

- editing;
- debugging;
- small calculations;
- exploratory programming.

Others are naturally batch-like:

- long numerical jobs;
- large data transformations;
- production runs;
- offline printing.

The real transition is therefore not:

```text
batch -> time-sharing
```

as a clean replacement.

It is:

```text
one machine
-> multiple service modes
-> scheduling and isolation decide how they coexist
```

## The system must account for ownership

Once several people share one computer, resource usage becomes attributable.

The operating system needs concepts such as:

- user identity;
- session state;
- file ownership;
- CPU usage;
- storage allocation;
- terminal association;
- access control.

These are not all created by CTSS, nor should every modern concept be projected backward unchanged.

But time-sharing intensifies the need for them because the machine is no longer serving one job stream under one operator's control.

It is serving a community.

The operating system starts to look less like a loader and more like an institution.

## Reconstruction: why slow humans create multiplexing opportunity

The companion experiment [`../../experiments/time-sharing/`](../../experiments/time-sharing/) models a deliberately simple situation. By default, to approximate intermittent interaction, each user's request stream emits requests at a fixed start-to-start interval, and each request demands a short CPU burst:

```text
fixed request-start interval -> next request arrival
each request                -> short CPU burst
```

The script compares:

- the offered CPU load from one user's request stream;
- aggregating many users on one CPU;
- simple response-time behavior as the user population grows.

This default is an open-loop model: a scheduled request does not wait for the previous response before arriving. The legacy `--think` option retains that meaning.

The opt-in `--pause` mode instead closes the interaction loop:

```text
submit -> wait for response -> pause -> submit again
```

Each user has at most one outstanding request. The next arrival occurs at the previous completion plus the specified pause, so slower responses postpone later demand. The two modes share the same initial arrival vector when the positive interval and pause are equal. For example:

```bash
python experiments/time-sharing/time_sharing.py --users 2 --rounds 2 --pause 1 --cpu 1 --quantum 0.5 --trace
```

This synthetic run completes four requests with a mean response of 1.5 seconds and a makespan of 4.5 seconds. With `--think 1` in place of `--pause 1 --trace`, the same initial arrivals yield 2.125 seconds and 4 seconds respectively. The experiment README gives the complete trace and event-ordering rules. Statistics include startup and final drain, exclude any pause after the final response, and are not steady-state estimates. Neither mode reproduces CTSS scheduling, measured user behavior, or historical capacity.

Its purpose is to expose the economic intuition:

> a person can feel continuously connected to a computer while actually requiring only intermittent slices of computation.

## What breaks the illusion

Time-sharing works only while the multiplexing assumptions remain plausible.

The experience degrades when:

- too many users become CPU-bound at once;
- memory pressure causes excessive swapping;
- terminal I/O queues grow;
- a scheduler uses slices that are too long;
- context-switch overhead becomes too large;
- one job monopolizes scarce devices;
- storage latency dominates;
- protection failures threaten system integrity.

So 'interactive' is not a binary property.

It is an operating region.

A time-sharing system is responsive when workload, memory, scheduler, I/O, and user behavior all remain inside that region.

## A recurring modern pattern

The technologies are different, but the structure reappears in modern cloud and interactive services.

A shared infrastructure provider asks:

- how many mostly-idle users can one expensive machine support?
- how should short latency-sensitive work coexist with long background work?
- how much memory should remain resident?
- how much isolation is enough?
- when does contention become visible?

Time-sharing is not the same as modern virtualization or cloud computing.

But it is an important ancestor of the idea that **a centralized expensive resource can be partitioned into convincing individual experiences**.

## What this teaches us

CTSS makes several computing principles visible at once.

### Human latency can be an architectural requirement

A system can be inefficient for the user even while efficient for the machine.

### Protection enables social sharing

Timer interrupts, memory protection, and relocation are not merely technical tricks; they make mutually untrusted or simply fallible users coexist.

### Buffers reconcile timescales

A 110-baud terminal and a mainframe CPU cannot interact sensibly without decoupling.

### Secondary storage extends the illusion of presence

A user can remain logically logged in while their program is not physically resident in core.

### Scheduling becomes interface design

The allocation algorithm is experienced as responsiveness.

### Personal experience can precede personal ownership

Interactive files, commands, editing, and remote sessions can feel personal even when the hardware is shared.

The shift from batch to conversation was therefore not one software feature.

It required the computer to learn how to **interrupt, protect, remember, buffer, identify, schedule, and pretend**.

The pretense was powerful enough that each user could begin to think:

> this machine is here for me.

## References

[^ctss-paper]: Fernando J. Corbató, Marjorie Merwin-Daggett, Robert C. Daley, et al., “An Experimental Time-Sharing System,” *Proceedings of the 1962 Spring Joint Computer Conference*, pp. 335–344, DOI 10.1145/1460833.1460871.

[^ctss-guide]: MIT Computation Center, *The Compatible Time-Sharing System: A Programmer's Guide*, 1966 edition, digitized by the Multics History Project / MIT CSAIL, https://people.csail.mit.edu/saltzer/Multics/CTSS-Documents/CTSS_ProgrammersGuide_1966.pdf

[^ctss-tech]: Jerome H. Saltzer et al., *CTSS Technical Notes*, MIT Project MAC Technical Report MAC-TR-16, March 1965, https://web.mit.edu/saltzer/www/publications/TRs%2BTMs/Multics/TR-016.pdf

## Preservation note

MIT CSAIL's CTSS document collection explains that much of the surviving online documentation was scanned from paper by the Multics History Project, especially Roger Roach and Olin Sibert, with important material drawn from Jerome Saltzer's files and Bitsavers. See https://www.csail.mit.edu/ctss-documents

That preservation work is part of why detailed reconstruction of this system is possible today.

## Source notes

The CTSS paper, manuals, technical notes, memos, bulletins, and source listings are project-produced primary or near-primary technical evidence. They document CTSS well but naturally describe the system from the perspective of its creators and maintainers.

Claims about broad priority in time-sharing history require comparison with other contemporary projects and are deliberately avoided here.
