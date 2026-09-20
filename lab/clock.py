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
#: pool.ntp.org rate-limits this host and answers with Kiss-o'-Death packets, so it is not in
#: the default set. Four independent operators instead, and the consensus is a MEDIAN, so one
#: bad server cannot move it.
DEFAULT_SERVERS = ("time.google.com", "time.cloudflare.com", "time.apple.com", "time.nist.gov")


class NtpRejected(ValueError):
    """The server answered, but told us not to use the reply.

    RED TEAM 2026-09-20: five of twenty replies from pool.ntp.org came back as Kiss-o'-Death
    (leap indicator 3, stratum 0, refid 'RATE', transmit timestamp zero). Those parsed into an
    offset of -4e12 ms, and because a KoD reply is SHORT, the old consensus rule of "trust the
    shortest round trip" actively preferred them.
    """


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
    # Resolve BEFORE starting the clock: a DNS lookup inside t1..t4 biases the offset by half
    # the lookup time, which on a cold cache is tens of milliseconds.
    addr = socket.gethostbyname(server)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        t1 = time.time()
        s.sendto(packet, (addr, 123))
        data, _ = s.recvfrom(1024)
        t4 = time.time()
    finally:
        s.close()
    if len(data) < 48:
        raise NtpRejected(f"{server}: short reply, {len(data)} bytes")
    unpacked = struct.unpack("!12I", data[:48])
    li = (unpacked[0] >> 30) & 0x3
    mode = (unpacked[0] >> 24) & 0x7
    stratum = (unpacked[0] >> 16) & 0xFF
    refid = data[12:16]
    if li == 3 or stratum == 0:
        raise NtpRejected(f"{server}: kiss-o'-death or unsynchronised "
                          f"(li={li} stratum={stratum} refid={refid!r})")
    if mode != 4:
        raise NtpRejected(f"{server}: not a server reply (mode={mode})")
    if stratum > 15:
        raise NtpRejected(f"{server}: stratum {stratum} is not usable")
    t2 = unpacked[8] + unpacked[9] / 2**32 - NTP_EPOCH_DELTA   # server receive
    t3 = unpacked[10] + unpacked[11] / 2**32 - NTP_EPOCH_DELTA  # server transmit
    if unpacked[10] == 0:
        raise NtpRejected(f"{server}: zero transmit timestamp")
    offset = ((t2 - t1) + (t3 - t4)) / 2.0
    delay = (t4 - t1) - (t3 - t2)
    return ClockSample(server, offset * 1000.0, delay * 1000.0, t4)


def measure(servers: tuple[str, ...] = DEFAULT_SERVERS) -> list[ClockSample]:
    out = []
    for srv in servers:
        try:
            out.append(query(srv))
        except NtpRejected as exc:
            print(f"  [clock] rejected {exc}")
        except (OSError, struct.error, IndexError) as exc:
            print(f"  [clock] {srv} unreachable: {type(exc).__name__}")
    return out


def consensus(samples: list[ClockSample]) -> tuple[float, float]:
    """(offset_ms, uncertainty_ms) as the MEDIAN offset across servers.

    The previous rule took the sample with the shortest round trip, on the reasoning that the
    shortest path is least distorted by queueing. That is true among HONEST replies and
    catastrophic otherwise, because a rejection packet is the shortest reply of all. The median
    needs a majority to be wrong, and the uncertainty carries both the path asymmetry of the
    median sample and the disagreement between servers.
    """
    if not samples:
        return 0.0, float("inf")
    offsets = sorted(s.offset_ms for s in samples)
    mid = len(offsets) // 2
    median = offsets[mid] if len(offsets) % 2 else (offsets[mid - 1] + offsets[mid]) / 2.0
    closest = min(samples, key=lambda s: abs(s.offset_ms - median))
    spread = offsets[-1] - offsets[0]
    return median, closest.uncertainty_ms + spread / 2.0


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
