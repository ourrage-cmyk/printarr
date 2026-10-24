"""Decode real-time status replies (DLE EOT n) from the TM-T88V.

Bit layouts come from the ESC/POS Command Reference, dle_eot page (see
research/escpos-tm-t88v-command-reference-verified.md, section 2). Every reply byte has
bits 1 and 4 set and bits 0 and 7 clear. Only the bits named here are read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# (request n, bit mask, fault key, alert text). Any fault pauses the print queue.
FAULTS: tuple[tuple[int, int, str, str], ...] = (
    (1, 0x08, "offline", "printer offline"),
    (2, 0x04, "cover", "printer cover open"),
    (2, 0x40, "error", "printer error"),
    (3, 0x04, "recoverable", "recoverable error"),
    (3, 0x08, "cutter", "autocutter error"),
    (3, 0x20, "unrecoverable", "unrecoverable error, power off the printer"),
    (3, 0x40, "auto_recoverable", "auto-recoverable error"),
)
# Paper (n=4): bits 5-6 are the end sensor, bits 2-3 the near-end sensor.
# Paper-end stop (n=2, bit 5) is also a paper fault.
PAPER_END_MASK = 0x60
PAPER_NEAR_END_MASK = 0x0C
PAPER_STOP_MASK = 0x20  # n=2

# Alert text for each key. The recovery message is "<text> cleared" (see main.py).
FAULT_TEXT: dict[str, str] = {key: text for _, _, key, text in FAULTS}
FAULT_TEXT["paper"] = "paper out"

# The requests each key needs. If any of them got no answer, the key is not updated,
# so a silent printer never clears a fault that was already raised.
REQUESTS_FOR_KEY: dict[str, tuple[int, ...]] = {key: (n,) for n, _, key, _ in FAULTS}
REQUESTS_FOR_KEY["paper"] = (2, 4)
REQUESTS_FOR_KEY["paper_near_end"] = (4,)


@dataclass(frozen=True)
class PrinterStatus:
    """One decoded status poll. `known` lists the keys that the printer answered for."""

    faults: frozenset[str]
    warnings: frozenset[str]
    known: frozenset[str]

    @property
    def blocking(self) -> bool:
        """True while the queue must wait. Warnings never block."""
        return bool(self.faults)

    def is_fault(self, key: str) -> bool:
        return key in self.faults


def decode(answers: Mapping[int, int | None]) -> PrinterStatus:
    """Turn raw DLE EOT replies, {n: byte or None}, into fault and warning keys."""
    faults: set[str] = set()
    warnings: set[str] = set()
    known = {
        key for key, requests in REQUESTS_FOR_KEY.items()
        if all(answers.get(n) is not None for n in requests)
    }
    for n, mask, key, _text in FAULTS:
        value = answers.get(n)
        if value is not None and value & mask:
            faults.add(key)
    status2 = answers.get(2)
    if status2 is not None and status2 & PAPER_STOP_MASK:
        faults.add("paper")
    paper = answers.get(4)
    if paper is not None and paper & PAPER_END_MASK:
        faults.add("paper")
    if paper is not None and paper & PAPER_NEAR_END_MASK:
        warnings.add("paper_near_end")
    return PrinterStatus(frozenset(faults), frozenset(warnings), frozenset(known))
