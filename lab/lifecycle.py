"""Order lifecycle telemetry: every stage from signal to final fill, with attribution.

    signal -> risk check -> order created -> order sent -> broker ack -> first fill
           -> final fill, or reject, or cancel

Two clocks are involved and they must never be mixed carelessly. Stages inside this process
are measured with `time.perf_counter`, which is monotonic and immune to the system clock being
adjusted mid-order. Anything compared against a BROKER timestamp is a wall-clock comparison and
therefore carries the clock offset measured in `lab.clock`, which is subtracted before the
number is stored. A stage whose latency is smaller than the clock uncertainty is stored with
that flag set rather than reported as a measurement.

Nothing here can block or delay an order: every write is best effort and failures are swallowed
after being counted, because telemetry that can break execution is worse than no telemetry.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from lab import registry

#: Stages in the order they should occur. Used to compute adjacent-stage deltas.
STAGES = ("signal", "risk_start", "risk_done", "order_created", "order_sent", "broker_ack",
          "first_fill", "final_fill", "rejected", "cancelled")

#: Which deltas are worth naming. Each is (name, from_stage, to_stage).
SPANS = (
    ("decision_to_risk", "signal", "risk_start"),
    ("risk_engine", "risk_start", "risk_done"),
    ("order_build", "risk_done", "order_created"),
    ("internal_queue", "order_created", "order_sent"),
    ("order_transmission", "order_sent", "broker_ack"),
    ("time_to_first_fill", "order_sent", "first_fill"),
    ("time_to_complete_fill", "order_sent", "final_fill"),
    ("signal_to_fill", "signal", "final_fill"),
    ("time_to_reject", "order_sent", "rejected"),
)


@dataclass
class OrderLifecycle:
    """One order's timeline. Local stamps are monotonic; broker stamps are wall clock."""
    symbol: str
    side: str
    strategy: str = "unknown"
    experiment_id: str | None = None
    order_ref: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    local: dict[str, float] = field(default_factory=dict)      # stage -> perf_counter
    wall: dict[str, float] = field(default_factory=dict)       # stage -> unix time
    broker: dict[str, float] = field(default_factory=dict)     # stage -> broker's own stamp
    clock_offset_ms: float = 0.0
    clock_uncertainty_ms: float = float("inf")
    notes: dict = field(default_factory=dict)

    def mark(self, stage: str, broker_ts: float | None = None) -> None:
        """Record a stage now. `broker_ts` is the venue's own stamp in SECONDS, if it gave one."""
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        self.local[stage] = time.perf_counter()
        self.wall[stage] = time.time()
        if broker_ts is not None:
            self.broker[stage] = float(broker_ts)

    def use_clock(self, offset_ms: float, uncertainty_ms: float) -> None:
        self.clock_offset_ms = offset_ms
        self.clock_uncertainty_ms = uncertainty_ms

    def spans_ms(self) -> dict[str, float]:
        """Named stage-to-stage latencies, monotonic where both ends are local."""
        out = {}
        for name, a, b in SPANS:
            if a in self.local and b in self.local:
                out[name] = (self.local[b] - self.local[a]) * 1000.0
        return out

    def broker_gaps_ms(self) -> dict[str, tuple[float, str]]:
        """Local-versus-broker comparisons, clock corrected, each with an honesty note.

        `broker_ack - order_sent` measured across two machines is the only way to see the
        network leg, and it is exactly the subtraction that is invalid without a clock
        correction, so the correction and its uncertainty travel with the number.
        """
        from lab.clock import corrected_latency_ms
        out = {}
        for stage, bts in self.broker.items():
            if stage not in self.wall:
                continue
            raw_ms = (self.wall[stage] - bts) * 1000.0
            value, note = corrected_latency_ms(raw_ms, self.clock_offset_ms,
                                               self.clock_uncertainty_ms)
            out[f"{stage}_local_minus_broker"] = (value, note)
        return out

    def outcome(self) -> str:
        for stage in ("rejected", "cancelled", "final_fill", "first_fill", "order_sent"):
            if stage in self.local:
                return {"final_fill": "filled", "first_fill": "partially_filled"}.get(stage, stage)
        return "not_sent"

    def persist(self) -> dict:
        """Write every span to latency_events. Best effort: never let telemetry break an order."""
        recorded = {}
        try:
            for name, value in self.spans_ms().items():
                registry.record_latency(name, value, self.experiment_id, strategy=self.strategy,
                                        instrument=self.symbol, exchange="ctrader", mode="live",
                                        span_id=self.order_ref)
                recorded[name] = value
            for name, (value, note) in self.broker_gaps_ms().items():
                registry.record_latency(name, value, self.experiment_id, strategy=self.strategy,
                                        instrument=self.symbol, exchange="ctrader",
                                        mode=note[:32], span_id=self.order_ref)
                recorded[name] = value
        except Exception as exc:                      # noqa: BLE001
            self.notes["telemetry_error"] = f"{type(exc).__name__}: {exc}"
        self.notes["outcome"] = self.outcome()
        return recorded

    def report(self) -> str:
        lines = [f"order {self.order_ref} {self.side} {self.symbol} -> {self.outcome()}"]
        for name, value in self.spans_ms().items():
            lines.append(f"  {name:<24}{value:9.1f} ms")
        for name, (value, note) in self.broker_gaps_ms().items():
            suffix = "" if note == "ok" else f"   [{note}]"
            lines.append(f"  {name:<24}{value:9.1f} ms{suffix}")
        return "\n".join(lines)
