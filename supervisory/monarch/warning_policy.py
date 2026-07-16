"""Python port of APC_9056_WarningIntegration.vi — the warning → state policy.

Produces `STATE LIMITATION FROM WARNINGS` (the StateMachine input the A1 port
consumes) from channel values, per-channel limits, and the latching/clearing
rules. Transcribed from the per-frame export
(original-labview-codebase/APC_9056_WarningIntegration/, 2026-07-06).

Semantics, as read from the wiring:

* Warning LEVELS per channel (the VI's legend):
    0 = no warning
    1 = soft warning (self-cleared)
    2 = send to idle
    3 = send to motoring
    4 = send to safe and vent
* Fresh level = the highest i in 1..4 whose (enabled) threshold is crossed.
  A per-channel `sign` (+1/-1) sets the direction: the VI multiplies value and
  limits by sign and compares once, so sign=+1 trips when value > limit and
  sign=-1 trips when value < limit.
* Latching: each channel's level ratchets (element-wise max with the previous
  tick via a feedback node). A dedicated ClearSoftWarning pass drops a latched
  level 1 back to 0 once the fresh level is 0 (soft = self-clearing); levels
  >= 2 stay latched until an operator clear (APC_MASTER/SLAVE_ClearWarnings),
  which multiplies the latch by 0 (full reset — fresh levels repopulate on the
  next evaluation).
* Aggregation: max level over all channels (5 rasters + the merged cylinder
  warnings) -> mapping case {0/default: 3, 1: 3, 2: 2, 3: 1, 4: -1} =
  STATE LIMITATION FROM WARNINGS.
* The VI also stall-detects the 9049 and 9056-FPGA heartbeats (counter vs
  threshold 10), but — like the PC watchdog — the resulting booleans are
  front-panel indicators only; they do NOT feed the limitation. Reproduced
  here as `heartbeat_stalled()` for parity, kept out of the policy result
  (finding logged in docs/shadow-findings.md).

Simplification (noted): the VI merges CylPresWarnings/CylPresErrors bitfields
into per-kind cylinder warnings upstream of the max. This port accepts
already-merged cylinder LEVELS via `extra_levels` — the bitfield decode lives
with the 9049 contract when that gets modeled.

KNOWN GAPS vs the as-built (2026-07-14 print decode,
docs/9056-warning-policy-asbuilt.md — this port predates it):

* Per-state ARMING masks: the as-built arms/disarms channels by system state
  (the per-state arming tables); this port evaluates every channel in every
  state. No state input exists here yet.
* The 9049-side state gate (built + live-verified 2026-07-14, SIL-1 6c):
  late-combustion and misfire-from-IMEP flags are AND'd with
  `9049_Global_SYSTEMSTATE >= 2` upstream of the latches in
  CombCluster2Array. Any future port of the 9049 cylinder chain must include
  it, and remember the misfire checks are ONE-SIDED low-side (F3d).
* Also note W5 (as-built defect, not a port bug): on the 9056 the
  STATE LIMITATION FROM WARNINGS output is computed but NOT consumed by the
  StateMachine — only the watchdog clamp acts. This port models the intended
  behaviour, which is AHEAD of the as-built until W5 is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NO_LIMIT = 3  # level 0/1 -> no state restriction (FIRING allowed)

#: Warning level -> maximum permitted system state (the VI's mapping case).
LEVEL_TO_STATE_LIMIT: dict[int, int] = {0: 3, 1: 3, 2: 2, 3: 1, 4: -1}


def level_to_state_limit(level: int) -> int:
    """Mapping case semantics: unknown/other levels take the Default (3)."""
    return LEVEL_TO_STATE_LIMIT.get(int(level), NO_LIMIT)


@dataclass(frozen=True)
class ChannelLimits:
    """One channel's warning thresholds (one row of a Raster*_limits cluster).

    thresholds[i] is the level-(i+1) limit. sign=+1 warns above, -1 warns
    below. enabled[i] gates each level (the green per-level booleans).
    """

    thresholds: tuple[float, float, float, float]
    sign: int = 1
    enabled: tuple[bool, bool, bool, bool] = (True, True, True, True)

    def fresh_level(self, value: float) -> int:
        level = 0
        for i in range(4):
            if self.enabled[i] and self.sign * value > self.sign * self.thresholds[i]:
                level = i + 1
        return level


@dataclass
class WarningPolicy:
    """Stateful port of the warning integration: latching per channel, operator
    clear, aggregation, and the state-limit mapping. `step()` is the once-per-
    tick entry point (pure but for the explicit latch state it owns)."""

    channels: dict[str, ChannelLimits] = field(default_factory=dict)
    latched: dict[str, int] = field(default_factory=dict)
    extra_latched: dict[str, int] = field(default_factory=dict)

    def step(
        self,
        values: dict[str, float],
        extra_levels: dict[str, int] | None = None,
        operator_clear: bool = False,
    ) -> int:
        """Evaluate one tick; returns STATE LIMITATION FROM WARNINGS.

        values: channel value per configured channel name (missing channels
        keep their latch). extra_levels: pre-computed levels (e.g. merged
        cylinder warnings) that latch and aggregate identically.
        """
        if operator_clear:
            # the VI multiplies the latch by 0; fresh levels repopulate below
            self.latched = {k: 0 for k in self.latched}
            self.extra_latched = {k: 0 for k in self.extra_latched}

        for name, value in values.items():
            limits = self.channels.get(name)
            if limits is None:
                continue
            fresh = limits.fresh_level(value)
            prev = self.latched.get(name, 0)
            latched = max(prev, fresh)
            if latched == 1 and fresh == 0:
                latched = 0  # soft warnings self-clear (ClearSoftWarning)
            self.latched[name] = latched

        for name, fresh in (extra_levels or {}).items():
            prev = self.extra_latched.get(name, 0)
            latched = max(prev, int(fresh))
            if latched == 1 and fresh == 0:
                latched = 0
            self.extra_latched[name] = latched

        return level_to_state_limit(self.max_level())

    def max_level(self) -> int:
        levels = list(self.latched.values()) + list(self.extra_latched.values())
        return max(levels, default=0)

    @property
    def state_limitation(self) -> int:
        return level_to_state_limit(self.max_level())


@dataclass
class HeartbeatStallDetector:
    """The VI's 9049 / 9056-FPGA heartbeat stall check: a counter that
    increments while the heartbeat value is unchanged and trips at the
    threshold. NOTE: in the VI the result drives an indicator only — it does
    not feed the state limitation (docs/shadow-findings.md)."""

    threshold: int = 10
    _last: float | None = None
    _count: int = 0

    def update(self, heartbeat_value: float) -> bool:
        if self._last is not None and heartbeat_value == self._last:
            self._count += 1
        else:
            self._count = 0
        self._last = heartbeat_value
        return self._count >= self.threshold
