#!/usr/bin/env python3
"""Toy models for fixed arrivals or post-response pauses on a shared CPU.

The model does not reproduce CTSS scheduling. It illustrates why request streams
separated by long pauses and requiring short CPU bursts can share one processor
while users still perceive relatively quick service at modest load.
"""

from __future__ import annotations

import argparse
import heapq
import math
from collections import deque
from dataclasses import dataclass
from statistics import mean


@dataclass(order=True)
class Request:
    arrival: float
    user: int
    sequence: int
    cpu: float


@dataclass
class Metrics:
    completed: int
    mean_response: float
    max_response: float
    cpu_utilization: float
    makespan: float


def _require_positive_finite(name: str, value: float) -> None:
    """Reject values that cannot advance this discrete-event simulation."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


def per_user_offered_load(cpu_burst: float, request_interval: float) -> float:
    """Return one request stream's demand per fixed request-start interval."""
    _require_positive_finite("cpu_burst", cpu_burst)
    _require_positive_finite("request_interval", request_interval)
    return cpu_burst / request_interval


def offered_load(users: int, cpu_burst: float, request_interval: float) -> float:
    """Return aggregate demand for the arrivals produced by build_requests()."""
    return users * per_user_offered_load(cpu_burst, request_interval)


def build_requests(
    users: int, rounds: int, request_interval: float, cpu_burst: float
) -> list[Request]:
    """Create deterministic staggered interactive requests.

    Each user emits a request once per fixed request-start interval. Initial
    arrivals are staggered evenly so all users do not synchronize at t=0. CPU
    service and queueing do not move later arrivals.
    """
    _require_positive_finite("request_interval", request_interval)
    _require_positive_finite("cpu_burst", cpu_burst)

    requests: list[Request] = []
    spacing = request_interval / users if users else 0.0
    for user in range(users):
        first = user * spacing
        for sequence in range(rounds):
            requests.append(
                Request(
                    arrival=first + sequence * request_interval,
                    user=user,
                    sequence=sequence,
                    cpu=cpu_burst,
                )
            )
    requests.sort()
    return requests


def simulate_round_robin(requests: list[Request], quantum: float) -> Metrics:
    _require_positive_finite("quantum", quantum)
    for request in requests:
        if not math.isfinite(request.arrival) or request.arrival < 0:
            raise ValueError("request arrival must be a non-negative finite number")
        _require_positive_finite("request cpu", request.cpu)
    if not requests:
        return Metrics(0, 0.0, 0.0, 0.0, 0.0)

    pending = list(requests)
    ready: list[tuple[int, int, float, float]] = []
    index = 0
    now = 0.0
    busy = 0.0
    completion_response: list[float] = []
    tie = 0

    while index < len(pending) or ready:
        if not ready and index < len(pending) and now < pending[index].arrival:
            now = pending[index].arrival

        while index < len(pending) and pending[index].arrival <= now + 1e-12:
            req = pending[index]
            heapq.heappush(ready, (tie, req.user, req.cpu, req.arrival))
            tie += 1
            index += 1

        if not ready:
            continue

        order, user, remaining, arrival = heapq.heappop(ready)
        run = min(quantum, remaining)
        now += run
        busy += run
        remaining -= run

        while index < len(pending) and pending[index].arrival <= now + 1e-12:
            req = pending[index]
            heapq.heappush(ready, (tie, req.user, req.cpu, req.arrival))
            tie += 1
            index += 1

        if remaining <= 1e-12:
            completion_response.append(now - arrival)
        else:
            heapq.heappush(ready, (tie, user, remaining, arrival))
            tie += 1

    makespan = now
    return Metrics(
        completed=len(completion_response),
        mean_response=sum(completion_response) / len(completion_response),
        max_response=max(completion_response),
        cpu_utilization=busy / makespan if makespan else 0.0,
        makespan=makespan,
    )


@dataclass(frozen=True)
class CompletedRequest:
    user: int
    sequence: int
    arrival: float
    completion: float
    cpu: float


@dataclass(frozen=True)
class ServiceSlice:
    user: int
    sequence: int
    start: float
    end: float
    cpu: float


@dataclass
class ClosedLoopResult:
    metrics: Metrics
    completions: tuple[CompletedRequest, ...]
    slices: tuple[ServiceSlice, ...]
    busy_time: float
    peak_outstanding: int


def _closed_loop_duration(name: str, value: float, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        bound = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {bound} finite number")
    return value


def _advance_closed_loop_time(now: float, duration: float) -> float:
    later = now + duration
    if not math.isfinite(later) or later <= now:
        raise ValueError("time increment is not representable; rescale the workload")
    return later


def simulate_closed_loop(
    users: int,
    rounds: int,
    pause: float,
    cpu_burst: float,
    quantum: float,
    *,
    trace: bool = False,
) -> ClosedLoopResult:
    """Run finite users who submit again only after completion plus a pause.

    The one-time initial arrival is user * (pause / users), matching the
    open-loop generator's initial phases when its interval equals pause > 0.
    Zero pause starts everyone at zero, in user order. Due arrivals join before
    an unfinished slice is requeued; a zero-pause successor joins afterwards.
    Statistics cover time zero through the last completion, not steady state.

    Counts must be positive integers; pause may be zero, CPU/quantum may not.
    Floating-point roundoff remains possible, but no absolute epsilon admits
    future work or discards remaining service. Nonfinite or nonadvancing time
    and service arithmetic raises ValueError rather than returning false data.
    Trace only controls slice recording, never scheduling or completions.
    """
    for name, value in (("users", users), ("rounds", rounds)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    pause = _closed_loop_duration("pause", pause, allow_zero=True)
    cpu_burst = _closed_loop_duration("cpu_burst", cpu_burst)
    quantum = _closed_loop_duration("quantum", quantum)
    try:
        spacing = pause / users
    except OverflowError as error:
        raise ValueError("initial spacing is not representable") from error
    if pause > 0 and spacing == 0:
        raise ValueError("initial spacing is not representable")

    pending: list[Request] = []
    previous = -1.0
    for user in range(users):
        first = user * spacing
        if not math.isfinite(first) or (pause > 0 and first <= previous):
            raise ValueError("initial arrival spacing is not representable")
        pending.append(Request(first, user, 0, cpu_burst))
        previous = first
    heapq.heapify(pending)
    ready: deque[tuple[Request, float]] = deque()
    active: set[int] = set()
    completions: list[CompletedRequest] = []
    slices: list[ServiceSlice] = []
    peak_outstanding = 0
    now = busy = 0.0

    def admit_arrivals() -> None:
        nonlocal peak_outstanding
        while pending and pending[0].arrival <= now:
            request = heapq.heappop(pending)
            ready.append((request, request.cpu))
            active.add(request.user)
        peak_outstanding = max(peak_outstanding, len(active))

    while pending or ready:
        if not ready:
            now = max(now, pending[0].arrival)
        admit_arrivals()
        request, remaining = ready.popleft()
        exhausted = remaining <= quantum
        run = remaining if exhausted else quantum
        left = 0.0 if exhausted else remaining - run
        if not exhausted and left >= remaining:
            raise ValueError("remaining service decrement is not representable")
        start = now
        now = _advance_closed_loop_time(now, run)
        busy = _advance_closed_loop_time(busy, run)
        if trace:
            slices.append(ServiceSlice(request.user, request.sequence, start, now, run))
        admit_arrivals()
        if exhausted:
            completions.append(CompletedRequest(
                request.user, request.sequence, request.arrival, now, request.cpu
            ))
            active.remove(request.user)
            if request.sequence + 1 < rounds:
                arrival = _advance_closed_loop_time(now, pause) if pause else now
                heapq.heappush(pending, Request(
                    arrival, request.user, request.sequence + 1, cpu_burst
                ))
        else:
            ready.append((request, left))

    responses = [request.completion - request.arrival for request in completions]
    # statistics.mean accumulates floats exactly before division, avoiding both
    # raw-sum overflow and underflow from dividing tiny responses individually.
    mean_response = mean(responses)
    metrics = Metrics(len(completions), mean_response, max(responses), busy / now, now)
    return ClosedLoopResult(metrics, tuple(completions), tuple(slices), busy, peak_outstanding)


def _print_closed_loop(args: argparse.Namespace, result: ClosedLoopResult) -> None:
    metrics = result.metrics
    print("Closed-loop interactive sharing toy model")
    print(f"users:                 {args.users}")
    print(f"requests/user:         {args.rounds}")
    print(f"post-response pause:    {args.pause:.3f} s")
    print(f"CPU burst/request:     {args.cpu:.3f} s")
    print(f"round-robin quantum:   {args.quantum:.3f} s")
    print("initial phase:         user * (pause / users)")
    print()
    print("simulated shared CPU (finite run, including startup and drain)")
    print(f"  completed requests:  {metrics.completed}")
    print(f"  mean response time:  {metrics.mean_response:.4f} s")
    print(f"  max response time:   {metrics.max_response:.4f} s")
    print(f"  observed utilization:{metrics.cpu_utilization * 100:7.3f}%")
    print(f"  modeled makespan:    {metrics.makespan:.3f} s")
    print(f"  CPU service:         {result.busy_time:.3f} s")
    print(f"  peak outstanding:    {result.peak_outstanding} / {args.users} users")
    print()
    print("A slower response postpones that user's next request; no final pause is charged.")
    print("Synthetic timings and round robin are not CTSS measurements or its scheduler.")
    if args.trace:
        print("\ncompletion trace (user/request are zero-based; seconds)")
        print(f"{'user':>6} {'request':>8} {'arrival':>12} {'completion':>12} {'response':>12}")
        for request in result.completions:
            print(f"{request.user:6d} {request.sequence:8d} {request.arrival:12.6g} "
                  f"{request.completion:12.6g} {request.completion - request.arrival:12.6g}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare fixed arrivals or post-response pauses on a shared CPU."
    )
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=20)
    arrivals = parser.add_mutually_exclusive_group()
    arrivals.add_argument(
        "--think",
        dest="request_interval",
        metavar="SECONDS",
        type=float,
        default=10.0,
        help="fixed seconds between request starts (open-loop)",
    )
    arrivals.add_argument(
        "--pause", metavar="SECONDS", type=float,
        help="seconds after each response before resubmitting (closed-loop; may be zero)",
    )
    parser.add_argument("--trace", action="store_true", help="print the --pause completion trace")
    parser.add_argument(
        "--cpu", type=float, default=0.05, help="CPU seconds per request"
    )
    parser.add_argument(
        "--quantum", type=float, default=0.02, help="round-robin quantum seconds"
    )
    args = parser.parse_args()

    if args.users < 1 or args.rounds < 1:
        parser.error("--users and --rounds must be positive")
    if args.trace and args.pause is None:
        parser.error("--trace requires --pause")
    if args.pause is not None:
        try:
            closed = simulate_closed_loop(
                args.users, args.rounds, args.pause, args.cpu, args.quantum,
                trace=args.trace,
            )
        except ValueError as error:
            parser.error(str(error))
        _print_closed_loop(args, closed)
        return
    if any(
        not math.isfinite(value) or value <= 0
        for value in (args.request_interval, args.cpu, args.quantum)
    ):
        parser.error("--think, --cpu, and --quantum must be positive finite numbers")

    single = per_user_offered_load(args.cpu, args.request_interval)
    load = offered_load(args.users, args.cpu, args.request_interval)
    requests = build_requests(args.users, args.rounds, args.request_interval, args.cpu)
    metrics = simulate_round_robin(requests, args.quantum)

    print("Interactive sharing toy model")
    print(f"users:                 {args.users}")
    print(f"requests/user:         {args.rounds}")
    print(f"request-start interval: {args.request_interval:.3f} s")
    print(f"CPU burst/request:     {args.cpu:.3f} s")
    print(f"round-robin quantum:   {args.quantum:.3f} s")
    print()
    print(f"one user's offered load:      {single * 100:7.3f}% of one CPU")
    print(f"aggregate offered load:      {load * 100:7.3f}% of one CPU")
    print()
    print("simulated shared CPU")
    print(f"  completed requests:  {metrics.completed}")
    print(f"  mean response time:  {metrics.mean_response:.4f} s")
    print(f"  max response time:   {metrics.max_response:.4f} s")
    print(f"  observed utilization:{metrics.cpu_utilization * 100:7.3f}%")
    print(f"  modeled makespan:    {metrics.makespan:.3f} s")
    print()

    if load < 0.5:
        print(
            "Interpretation: substantial spare CPU capacity remains in this toy workload."
        )
    elif load < 1.0:
        print("Interpretation: the toy workload is busy but below nominal saturation.")
    else:
        print(
            "Interpretation: offered demand reaches/exceeds one CPU; queueing pressure is expected."
        )


if __name__ == "__main__":
    main()
