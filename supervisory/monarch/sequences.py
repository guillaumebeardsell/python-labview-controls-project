"""MONARCH sequences: the executor binding + draft procedures (Phase D).

SequenceExecutor couples a SequenceRunner to the MonarchCommander: each tick it
runs the sequence's pure decision, applies the resulting intent changes via
commander.modify(), and aborts the sequence if command authority is lost.
Run it in the same Supervisor as the commander, **listed before it**, so the
changes land in the frame the commander emits that same tick.

The draft procedures below are exactly that — DRAFTS, built to the D0 template
with every unconfirmed number in a SequenceConfig marked `# TBD(team)`. They
run closed-loop against the sim plant today; the team's D0 review replaces the
TBDs and adds/corrects steps. Confirmations use only signals that exist:
system_state, limited_settings, and the telemetry `plant` dict (sim-provided;
the real gateway grows tags per the phase-D LabVIEW note).

Safety notes encoded here:
  * every abort lands on `safe_landing` (feeds cut + vents commanded open +
    request SAFE-ward) — the combustion invariant's belt to the limiter's
    braces;
  * purge runs in MOTORING because the MAX-LEVEL table only enables the Ar
    feed (level 2) from MOTORING up;
  * a `no_unexpected_safe` invariant aborts any sequence the instant the
    StateMachine forces SAFE underneath it (e-stop, warnings, watchdog).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..engine import CommandRequest, PlantView, StateMachine
from ..sequencing import Action, Hold, Invariant, Sequence, SequenceRunner, Status
from .commander import MonarchCommander
from .control_settings import ControlSettings, SystemState
from .telemetry import MonarchTelemetry

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ executor


class SequenceExecutor(StateMachine):
    """Runs one sequence at a time through the commander's intent."""

    name = "monarch_sequences"

    def __init__(self, commander: MonarchCommander) -> None:
        self.commander = commander
        self.runner: SequenceRunner | None = None
        self._had_authority = False

    # ---- operator surface -------------------------------------------------
    def load(self, sequence: Sequence, **runner_kwargs) -> SequenceRunner:
        if self.runner is not None and self.runner.status in (Status.RUNNING, Status.HOLDING):
            raise RuntimeError(f"sequence {self.runner.sequence.name!r} is still active")
        self.runner = SequenceRunner(sequence, **runner_kwargs)
        self._had_authority = False
        return self.runner

    def start(self) -> None:
        if self.runner is None:
            raise RuntimeError("no sequence loaded")
        self.runner.start()

    def abort(self, reason: str = "operator") -> None:
        if self.runner is not None:
            self.runner.abort(reason)

    def confirm_hold(self) -> None:
        if self.runner is not None:
            self.runner.confirm_hold()

    @property
    def status(self) -> Status:
        return self.runner.status if self.runner is not None else Status.IDLE

    # ---- engine hook -------------------------------------------------------
    def step(self, view: PlantView) -> list[CommandRequest]:
        r = self.runner
        if r is None or r.status not in (Status.RUNNING, Status.HOLDING):
            return []
        if not self.commander.commanding:
            if not self._had_authority:
                return []  # authority not yet established: sequence waits at step 0
            # authority HELD and then lost (source flip, staleness): the plant
            # is already holding per the LabVIEW side; end deterministically.
            r.abort("lost command authority")
        else:
            self._had_authority = True
        tm = view.telemetry if isinstance(view.telemetry, MonarchTelemetry) else None
        res = r.tick(view.now, tm, view.stale or tm is None)
        for change in res.changes:
            if self.commander.commanding:
                self.commander.modify(change)
            else:
                log.warning("sequence change dropped (no authority): %s", res.active_label)
        if res.status in (Status.DONE, Status.ABORTED):
            log.info("sequence %r -> %s%s", r.sequence.name, res.status.value,
                     f" ({res.abort_reason})" if res.abort_reason else "")
        return []  # the commander emits the actual command


# ------------------------------------------------------------- change helpers


def cut_feeds(s: ControlSettings) -> None:
    p = s.pid_control_references
    p.ng.mode = 0
    p.ar.mode = 0
    p.o2.mode = 0
    p.ng_valve = False
    p.ar_valve = False
    p.o2_valve = False


def open_vents(s: ControlSettings) -> None:
    p = s.pid_control_references
    p.intake_vent = False  # False = open (1 = closed)
    p.cross_vent = False
    p.exhaust_vent = False


def safe_landing(s: ControlSettings) -> None:
    """The declared abort landing for every draft: feeds cut, vents commanded
    open, state request withdrawn to STAND_BY. (The LabVIEW limiter enforces
    the same lineup independently in SAFE/STAND_BY — belt and braces.)"""
    cut_feeds(s)
    open_vents(s)
    s.requested_mode = SystemState.STAND_BY


def request_mode(mode: SystemState):
    def change(s: ControlSettings) -> None:
        s.requested_mode = mode
    return change


def state_is(state: SystemState):
    def cond(tm: MonarchTelemetry) -> bool:
        return int(tm.system_state) == int(state)
    return cond


def plant_below(tag: str, threshold: float):
    def cond(tm: MonarchTelemetry) -> bool:
        value = (tm.plant or {}).get(tag)
        return value is not None and value < threshold
    return cond


def plant_within(tag: str, target: float, band: float):
    def cond(tm: MonarchTelemetry) -> bool:
        value = (tm.plant or {}).get(tag)
        return value is not None and abs(value - target) <= band
    return cond


no_unexpected_safe = Invariant(
    "no unexpected SAFE",
    lambda tm: int(tm.system_state) > int(SystemState.SAFE),
)


# ------------------------------------------------------------ draft sequences


@dataclass(frozen=True)
class SequenceConfig:
    """Every number here is provisional until the D0 review signs it off."""

    ambient_bar: float = 1.0  # TBD(team): site ambient reference
    depressurize_band_bar: float = 0.1  # TBD(team)
    depressurize_timeout_s: float = 120.0  # TBD(team)
    mode_change_timeout_s: float = 15.0  # TBD(team)
    settings_ack_timeout_s: float = 5.0  # TBD(team)
    purge_o2_target_pct: float = 2.0  # TBD(team): acceptable O2 for purge-complete
    purge_timeout_s: float = 300.0  # TBD(team)
    coolant_target_c: float = 60.0  # TBD(team)
    oil_target_c: float = 70.0  # TBD(team)
    temp_band_c: float = 3.0  # TBD(team)
    warmup_timeout_s: float = 900.0  # TBD(team)


def venting(cfg: SequenceConfig = SequenceConfig()) -> Sequence:
    """Vent the working-fluid loop to ambient. First on the bench (valves only)."""
    return Sequence(
        name="venting",
        description="Cut gas feeds, drop to STAND_BY, open all vents, "
                    "confirm WF pressure at ambient.",
        steps=(
            Action("cut gas feeds", change=cut_feeds,
                   confirm=lambda tm: tm.limited_settings is None or (
                       tm.limited_settings.pid_control_references.ng.mode == 0
                       and tm.limited_settings.pid_control_references.ar.mode == 0
                       and tm.limited_settings.pid_control_references.o2.mode == 0),
                   timeout_s=cfg.settings_ack_timeout_s),
            Action("request STAND_BY", change=request_mode(SystemState.STAND_BY),
                   confirm=lambda tm: int(tm.system_state) <= int(SystemState.STAND_BY),
                   timeout_s=cfg.mode_change_timeout_s),
            Action("open vents", change=open_vents,
                   confirm=lambda tm: tm.limited_settings is None or not (
                       tm.limited_settings.pid_control_references.intake_vent
                       or tm.limited_settings.pid_control_references.cross_vent
                       or tm.limited_settings.pid_control_references.exhaust_vent),
                   timeout_s=cfg.settings_ack_timeout_s),
            Action("wait for depressurization",
                   confirm=plant_below("WF-PT-004_bar",
                                       cfg.ambient_bar + cfg.depressurize_band_bar),
                   timeout_s=cfg.depressurize_timeout_s),
        ),
        abort_change=safe_landing,
    )


def purge(cfg: SequenceConfig = SequenceConfig()) -> Sequence:
    """Displace air with argon. Ar feed needs MOTORING (MAX-LEVEL table)."""
    return Sequence(
        name="purge",
        description="Step to MOTORING (Ar feed enabled there), flow argon with "
                    "the exhaust vent open, confirm O2 below target, secure.",
        steps=(
            Action("request MOTORING", change=request_mode(SystemState.MOTORING),
                   confirm=state_is(SystemState.MOTORING),
                   timeout_s=cfg.mode_change_timeout_s),
            Action("argon flow, exhaust vent open",
                   change=lambda s: (
                       setattr(s.pid_control_references.ar, "mode", 1),
                       setattr(s.pid_control_references, "ar_valve", True),
                       setattr(s.pid_control_references, "exhaust_vent", False),
                       setattr(s.pid_control_references, "intake_vent", True),
                   ),
                   confirm=lambda tm: tm.limited_settings is None
                   or tm.limited_settings.pid_control_references.ar.mode >= 1,
                   timeout_s=cfg.settings_ack_timeout_s),
            Action("wait for O2 displacement",
                   confirm=plant_below("WF-OA-001_O2pct", cfg.purge_o2_target_pct),
                   timeout_s=cfg.purge_timeout_s),
            Hold("verify purge", "Operator: confirm analyzer reading and lineup "
                                 "before securing the purge."),
            Action("secure: cut feeds", change=cut_feeds,
                   confirm=lambda tm: tm.limited_settings is None
                   or tm.limited_settings.pid_control_references.ar.mode == 0,
                   timeout_s=cfg.settings_ack_timeout_s),
            Action("back to STAND_BY", change=request_mode(SystemState.STAND_BY),
                   confirm=lambda tm: int(tm.system_state) <= int(SystemState.STAND_BY),
                   timeout_s=cfg.mode_change_timeout_s),
        ),
        abort_change=safe_landing,
        invariants=(no_unexpected_safe,),
    )


def thermal_warmup(cfg: SequenceConfig = SequenceConfig()) -> Sequence:
    """Bring coolant/oil to operating temperature (allowed from STAND_BY)."""
    return Sequence(
        name="thermal_warmup",
        description="Enable thermal loops closed-loop with target refs; wait "
                    "for temperatures; operator verifies stability.",
        steps=(
            Action("request STAND_BY", change=request_mode(SystemState.STAND_BY),
                   confirm=lambda tm: int(tm.system_state) >= int(SystemState.STAND_BY),
                   timeout_s=cfg.mode_change_timeout_s),
            Action("enable thermal loops",
                   change=lambda s: (
                       setattr(s.pid_control_references.tcoolant, "mode", 2),
                       setattr(s.pid_control_references.tcoolant, "ec_tt_001_ref",
                               cfg.coolant_target_c),
                       setattr(s.pid_control_references.toil, "mode", 2),
                       setattr(s.pid_control_references.toil, "eo_tt_001_ref",
                               cfg.oil_target_c),
                   ),
                   confirm=lambda tm: tm.limited_settings is None
                   or tm.limited_settings.pid_control_references.tcoolant.mode >= 1,
                   timeout_s=cfg.settings_ack_timeout_s),
            Action("wait for coolant temperature",
                   confirm=plant_within("EC-TT-001_degC", cfg.coolant_target_c,
                                        cfg.temp_band_c),
                   timeout_s=cfg.warmup_timeout_s),
            Action("wait for oil temperature",
                   confirm=plant_within("EO-TT-001_degC", cfg.oil_target_c,
                                        cfg.temp_band_c),
                   timeout_s=cfg.warmup_timeout_s),
            Hold("verify stability", "Operator: confirm temperatures stable "
                                     "before declaring warm-up complete."),
        ),
        abort_change=safe_landing,
        invariants=(no_unexpected_safe,),
    )


DRAFT_SEQUENCES = {
    "venting": venting,
    "purge": purge,
    "thermal_warmup": thermal_warmup,
}
