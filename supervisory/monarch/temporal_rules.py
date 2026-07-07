"""Temporal warning rules (Phase E2) — the layer the original developer flagged
as needed but never built.

A TemporalRule is DATA: "WHEN <predicate on telemetry> FOR <duration> WHILE
<state set> ⇒ <action>". The engine evaluates rules each tick with explicit
time (pure, testable with synthetic time series) and produces:
  * a state cap (min over tripped cap-rules), to be MIN'd into the warnings
    limit the same way everything else clamps, and
  * alerts (operator messages) for alert-rules.

These are a SUPERVISORY layer on top of LabVIEW's instantaneous per-channel
trips — never a replacement (the LabVIEW warning integration keeps running
unchanged underneath). Rules live in a reviewed table (see EXAMPLE_RULES);
the team supplies real durations/thresholds during commissioning.

Latching follows the house convention: a tripped cap-rule stays tripped until
`operator_clear()` (matching APC_MASTER_ClearWarnings semantics); alert-rules
re-arm when their condition clears.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

NO_LIMIT = 3

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemporalRule:
    """One row of the reviewed rule table."""

    name: str
    predicate: Callable[[object], bool]  # takes the telemetry frame
    for_s: float  # how long predicate must hold continuously
    while_states: frozenset[int] = frozenset({0, 1, 2, 3})  # states where armed
    cap_state: int | None = None  # tripped ⇒ cap max state to this (None = alert only)
    message: str = ""


@dataclass
class _RuleState:
    since: float | None = None  # when the predicate became continuously true
    tripped: bool = False


@dataclass
class TemporalRuleEngine:
    rules: tuple[TemporalRule, ...] = ()
    _states: dict[str, _RuleState] = field(default_factory=dict)

    def operator_clear(self) -> None:
        """Clear latched cap-rules (mirrors APC_MASTER_ClearWarnings)."""
        for st in self._states.values():
            st.tripped = False
            st.since = None

    def step(self, now: float, telemetry, system_state: int) -> tuple[int, list[str]]:
        """Evaluate all rules; returns (state_cap, new_alerts). state_cap is
        NO_LIMIT when nothing is tripped."""
        cap = NO_LIMIT
        alerts: list[str] = []
        for rule in self.rules:
            st = self._states.setdefault(rule.name, _RuleState())
            armed = system_state in rule.while_states
            try:
                holds = armed and bool(rule.predicate(telemetry))
            except Exception:
                log.exception("temporal rule %r predicate raised; treating as holding", rule.name)
                holds = armed  # fail toward caution
            if holds:
                if st.since is None:
                    st.since = now
                if not st.tripped and now - st.since >= rule.for_s:
                    st.tripped = True
                    alerts.append(f"{rule.name}: {rule.message or 'tripped'}")
                    log.warning("temporal rule tripped: %s", rule.name)
            else:
                st.since = None
                if rule.cap_state is None:
                    st.tripped = False  # alert-only rules re-arm on clear
            if st.tripped and rule.cap_state is not None:
                cap = min(cap, rule.cap_state)
        return cap, alerts

    def tripped(self) -> list[str]:
        return [name for name, st in self._states.items() if st.tripped]


def _plant(tm, tag: str):
    return (getattr(tm, "plant", None) or {}).get(tag)


# ---------------------------------------------------------------------------
# EXAMPLE rule table — structure demonstration with the report's examples.
# Every number is TBD(team); nothing loads these by default.
# ---------------------------------------------------------------------------
EXAMPLE_RULES: tuple[TemporalRule, ...] = (
    TemporalRule(
        name="oil pressure low while running",
        predicate=lambda tm: (_plant(tm, "EO-PT-001_bar") or 99.0) < 1.0,  # TBD(team)
        for_s=5.0,  # TBD(team)
        while_states=frozenset({1, 2, 3}),  # ≥ MOTORING
        cap_state=1,  # send to motoring   TBD(team)
        message="oil pressure below limit for 5 s while running",
    ),
    TemporalRule(
        name="coolant not moving while thermal loops active",
        predicate=lambda tm: (_plant(tm, "EC-FC-001_pct") or 100.0) < 5.0,  # TBD(team)
        for_s=10.0,  # TBD(team)
        while_states=frozenset({0, 1, 2, 3}),
        cap_state=None,  # alert only until the team confirms the reaction
        message="coolant flow near zero for 10 s with loops enabled",
    ),
)
