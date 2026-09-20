"""Clock discipline. Without it, every latency number in this project is a guess.

On 2026-09-20 the logger began recording the broker's event timestamp and the difference to our
receive time was reported as "market data latency": BTCUSD 216 ms, ETHUSD 285 ms. That
subtraction is only valid if our clock agrees with theirs. Windows syncs to time.windows.com
by default, historically to within seconds rather than milliseconds, and a 200 ms offset would
have produced exactly the numbers above out of nothing.

So this module measures our offset against public NTP servers, stores it, and gives the
latency tools a correction plus an honest uncertainty. A latency figure smaller than the clock
uncertainty is not a measurement.

NTP in 40 lines rather than a dependency: the packet is 48 bytes and the four timestamps it
returns are enough for the standard offset and delay formulas.
"""
from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass

NTP_EPOCH_DELTA = 2208988800  # seconds between 1900 (NTP) and 1970 (unix)
DEFAULT_SERVERS = ("time.google.com", "pool.ntp.org", "time.cloudflare.com")


@dataclass
class ClockSample:
    server: str
    offset_ms: float        # add this to the local clock to get true time
    round_trip_ms: float
    ts_utc: float

    @property
    def uncertainty_ms(self) -> float:
        """Half the round trip: the offset cannot be pinned finer than the path is symmetric."""
        return self.round_trip_ms / 2.0


def query(server: str = "time.google.com", timeout: float = 3.0) -> ClockSample:
    """One NTP exchange. Offset and delay by the standard four-timestamp formulas."""
    packet = b"\x1b" + 47 * b"\0"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        t1 = time.time()
        s.sendto(packet, (server, 123))
        data, _ = s.recvfrom(1024)
        t4 = time.time()
    finally:
        s.close()
    unpacked = struct.unpack("!12I", data[:48])
    t2 = unpacked[8] + unpacked[9] / 2**32 - NTP_EPOCH_DELTA   # server receive
    t3 = unpacked[10] + unpacked[11] / 2**32 - NTP_EPOCH_DELTA  # server transmit
    offset = ((t2 - t1) + (t3 - t4)) / 2.0
    delay = (t4 - t1) - (t3 - t2)
    return ClockSample(server, offset * 1000.0, delay * 1000.0, t4)


def measure(servers: tuple[str, ...] = DEFAULT_SERVERS) -> list[ClockSample]:
    out = []
    for srv in servers:
        try:
            out.append(query(srv))
        except (OSError, struct.error, IndexError):
            continue
    return out


def consensus(samples: list[ClockSample]) -> tuple[float, float]:
    """(offset_ms, uncertainty_ms) from the sample with the shortest round trip.

    The shortest path is the least contaminated by queueing in either direction, which is why
    NTP itself prefers it. Disagreement between servers is added to the uncertainty rather than
    averaged away.
    """
    if not samples:
        return 0.0, float("inf")
    best = min(samples, key=lambda s: s.round_trip_ms)
    spread = max(s.offset_ms for s in samples) - min(s.offset_ms for s in samples)
    return best.offset_ms, best.uncertainty_ms + spread / 2.0


def corrected_latency_ms(raw_ms: float, offset_ms: float, uncertainty_ms: float) -> tuple[float, str]:
    """Apply the clock correction and say whether what remains is a measurement or noise.

    raw_ms is local_receive - server_stamp. If our clock runs fast by `offset`, that inflates
    the apparent latency by the same amount, so the correction subtracts it.
    """
    corrected = raw_ms + offset_ms
    if abs(corrected) < uncertainty_ms:
        return corrected, (f"BELOW CLOCK UNCERTAINTY ({uncertainty_ms:.0f} ms): not measurable "
                           f"with this clock")
    if corrected < 0:
        return corrected, ("NEGATIVE after correction: the event appears to arrive before it "
                           "was stamped, so the broker's clock and ours disagree by more than "
                           "the correction explains")
    return corrected, "ok"
