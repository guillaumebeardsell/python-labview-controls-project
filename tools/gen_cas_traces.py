"""Generate synthetic crank-angle-synchronous (CAS) cylinder-pressure cycles
shaped exactly like the 9049 CAS DAQ output, plus a ground-truth metrics file.

    python tools/gen_cas_traces.py out_dir --cycles 10 --mode motored
    python tools/gen_cas_traces.py out_dir --mode mixed --fire-from 5 \
        --misfire 3:7 --knock 1:8:2.5 --seed 42

Purpose (see docs/9049-openloop-audit.md): feed the LabVIEW 9049 analysis
chain — `APC_9049_PressureAnalytics` and everything under it, or the PC-side
`APC_RunHRL_inPC` harness — with data whose IMEP/Pmax/CA50 are *known*, so the
chain's outputs (and the `9049_Global_CylPressError` warning thresholds) can be
verified before the engine ever turns. Each cycle is written as one CSV block
matching the DAQmx read the CAS loop performs.

Data shape (confirmed against the VI exports, 2026-07-08):
  - 2D array, 9 rows x 7200 columns, one engine cycle at 0.1 CAD/sample,
    values in bar (the DAQmx task applies sensor scales *before* the read, so
    synthetic data must already be in engineering units).
  - Rows 0-5 = Pcyl1..Pcyl6, row 6 = cyl-6 prechamber, row 7 = system
    pressure, row 8 = exhaust pressure.
  - Raw rows share one engine-absolute frame. `APC_9049_PPhaseCorrection`
    re-windows each cylinder at sample offsets [0, 4800, 2400, 6000, 1200,
    3600] (firing order 1-5-3-6-2-4) so its firing TDC lands at sample 3600 of
    its own -360..+359.9 CADATDC frame. The generator therefore builds each
    cylinder in its own frame (TDC at sample 3600) and circularly delays it by
    the cylinder's offset: raw[i] = cyl[(i - offset) % 7200].
  - The exhaust row must agree with each cylinder over its pegging window
    (samples 6900-7100 of the cylinder frame = +330..+350 CADATDC), because
    `APC_9049_HRL_pegging` re-references Pcyl to Pexh there.

Geometry/thermo defaults are PLACEHOLDERS — set the real MONARCH values
(bore/stroke/rod/CR and the working-fluid kappas) before comparing IMEP
magnitudes against LabVIEW. Phasing, shapes, and signs are valid regardless.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

N_SAMPLES = 7200  # one cycle at 0.1 CAD
CAD_STEP = 0.1
TDC_INDEX = 3600  # firing TDC in the per-cylinder frame (-360..+359.9 CADATDC)
CYL_OFFSETS = [0, 4800, 2400, 6000, 1200, 3600]  # raw-frame sample delay, cyl 1..6
ROWS = ["Pcyl1", "Pcyl2", "Pcyl3", "Pcyl4", "Pcyl5", "Pcyl6", "Ppre", "Psyst", "Pexh"]
PEGGING_WINDOW = (6900, 7100)  # cylinder-frame samples where Pcyl must ~= Pexh
IMEPG_WINDOW = (1800, 5400)  # compression+power, CAD 180..540 in the HRL's indexing


@dataclass
class Geometry:
    """Slider-crank geometry (SI). Defaults are placeholders, not MONARCH."""

    bore_m: float = 0.130
    stroke_m: float = 0.150
    conrod_m: float = 0.255
    compression_ratio: float = 12.0
    pin_offset_m: float = 0.0


def volume_curve(geom: Geometry) -> list[float]:
    """Cylinder volume [m^3] per cylinder-frame sample (TDC at sample 3600).

    Uses the exact slider-crank with crankpin offset (the LabVIEW
    `APC_9049_HRL_volume` approximates this — author-flagged 'FIX STROKE
    CALC' — so absolute IMEP from LabVIEW may carry a small bias vs truth).
    """
    r = geom.stroke_m / 2.0
    l = geom.conrod_m
    e = geom.pin_offset_m
    ap = math.pi * (geom.bore_m / 2.0) ** 2

    def lift(theta_rad: float) -> float:
        return l + r - r * math.cos(theta_rad) - math.sqrt(l**2 - (r * math.sin(theta_rad) - e) ** 2)

    lifts = []
    for i in range(N_SAMPLES):
        theta_atdc = (i - TDC_INDEX) * CAD_STEP
        lifts.append(lift(math.radians(theta_atdc)))
    s_min, s_max = min(lifts), max(lifts)
    vd = ap * (s_max - s_min)  # true displacement (with offset)
    vc = vd / (geom.compression_ratio - 1.0)
    return [vc + ap * (s - s_min) for s in lifts]


def _blend(a: float, b: float, frac: float) -> float:
    """Cosine blend a->b for frac in 0..1."""
    return a + (b - a) * 0.5 * (1.0 - math.cos(math.pi * min(max(frac, 0.0), 1.0)))


def wiebe_mfb(theta_atdc: float, soc_atdc: float, dur_cad: float, m: float = 2.0, a: float = 6.908) -> float:
    if theta_atdc <= soc_atdc:
        return 0.0
    x = (theta_atdc - soc_atdc) / dur_cad
    if x >= 1.0:
        return 1.0
    return 1.0 - math.exp(-a * x ** (m + 1.0))


def cylinder_trace(
    volumes: list[float],
    p_int_bar: float,
    p_exh_bar: float,
    kappa_comp: float,
    kappa_exp: float,
    fired: bool = False,
    q_fired_j: float = 0.0,
    soc_atdc: float = -8.0,
    burn_dur_cad: float = 45.0,
    kappa_fired: float = 1.45,
) -> list[float]:
    """One clean cycle [bar] in the cylinder frame (sample 3600 = firing TDC).

    Motored: polytropic compression (kappa_comp) and re-expansion (kappa_exp,
    slightly HIGHER to mimic heat loss: anchored at the TDC state, a larger
    expansion exponent puts the expansion branch below the compression branch
    -> small negative gross IMEP). Fired:
    single-zone integration dP = (kappa-1)/V dQ - kappa P/V dV with a Wiebe
    burn, so the *apparent* heat release the LabVIEW HRL recovers matches the
    Wiebe input by construction. Gas exchange is modeled as levels with short
    cosine blends (no valve dynamics).
    """
    p = [0.0] * N_SAMPLES
    ivc, evo = 1800, 5400  # samples: -180 and +180 CADATDC

    # Intake (-360..-180): settle from p_exh to p_int over the first 60 CAD.
    for i in range(0, ivc):
        frac = (i * CAD_STEP) / 60.0
        p[i] = _blend(p_exh_bar, p_int_bar, frac) if frac < 1.0 else p_int_bar

    # Closed part (-180..+180).
    if not fired:
        v_ivc = volumes[ivc]
        for i in range(ivc, evo):
            kappa = kappa_comp if i <= TDC_INDEX else kappa_exp
            # Anchor expansion to the TDC state reached by compression.
            if i <= TDC_INDEX:
                p[i] = p_int_bar * (v_ivc / volumes[i]) ** kappa
            else:
                p_tdc = p_int_bar * (v_ivc / volumes[TDC_INDEX]) ** kappa_comp
                p[i] = p_tdc * (volumes[TDC_INDEX] / volumes[i]) ** kappa
    else:
        p[ivc] = p_int_bar
        for i in range(ivc, evo - 1):
            theta = (i - TDC_INDEX) * CAD_STEP
            theta_next = theta + CAD_STEP
            dq = q_fired_j * (
                wiebe_mfb(theta_next, soc_atdc, burn_dur_cad) - wiebe_mfb(theta, soc_atdc, burn_dur_cad)
            )
            v, dv = volumes[i], volumes[i + 1] - volumes[i]
            p_pa = p[i] * 1e5
            dp_pa = (kappa_fired - 1.0) / v * dq - kappa_fired * p_pa / v * dv
            p[i + 1] = (p_pa + dp_pa) / 1e5

    # Exhaust (+180..+360): decay from EVO pressure to p_exh over 60 CAD,
    # then hold p_exh (covers the pegging window 6900-7100).
    p_evo = p[evo - 1]
    for i in range(evo, N_SAMPLES):
        frac = ((i - evo) * CAD_STEP) / 60.0
        p[i] = _blend(p_evo, p_exh_bar, frac) if frac < 1.0 else p_exh_bar
    return p


def add_knock(trace: list[float], amp_bar: float, rpm: float, freq_hz: float = 6000.0,
              onset_atdc: float = 5.0, tau_cad: float = 15.0) -> list[float]:
    """Superpose a decaying knock oscillation after `onset_atdc`."""
    out = list(trace)
    cyc_per_cad = freq_hz / (6.0 * rpm)  # deg/s = 6*rpm
    start = TDC_INDEX + int(onset_atdc / CAD_STEP)
    for i in range(start, min(start + int(5 * tau_cad / CAD_STEP), N_SAMPLES)):
        d_cad = (i - start) * CAD_STEP
        out[i] += amp_bar * math.exp(-d_cad / tau_cad) * math.sin(2 * math.pi * cyc_per_cad * d_cad)
    return out


def metrics(trace_bar: list[float], volumes: list[float]) -> dict:
    """Ground-truth metrics the LabVIEW chain should reproduce.

    IMEPn = closed-contour integral p dV / Vd over the full cycle; IMEPg over
    samples 1800..5400 (CAD 180..540 = compression+power, matching
    APC_9049_HRL_IMEP); PMEP = IMEPn - IMEPg.
    """
    vd = max(volumes) - min(volumes)

    def pdv(lo: int, hi: int) -> float:
        w = 0.0
        for i in range(lo, hi - 1):
            w += 0.5 * (trace_bar[i] + trace_bar[i + 1]) * 1e5 * (volumes[i + 1] - volumes[i])
        return w

    imep_n = pdv(0, N_SAMPLES) / vd / 1e5
    imep_g = pdv(*IMEPG_WINDOW) / vd / 1e5
    pmax = max(trace_bar)
    return {
        "pmax_bar": round(pmax, 3),
        "pmax_atdc": round((trace_bar.index(pmax) - TDC_INDEX) * CAD_STEP, 1),
        "imep_n_bar": round(imep_n, 4),
        "imep_g_bar": round(imep_g, 4),
        "pmep_bar": round(imep_n - imep_g, 4),
    }


def ca50_truth(soc_atdc: float, burn_dur_cad: float, m: float = 2.0, a: float = 6.908) -> float:
    """CA50 [CADATDC] of the Wiebe burn (analytic inverse at MFB=0.5)."""
    return soc_atdc + burn_dur_cad * (math.log(2.0) / a) ** (1.0 / (m + 1.0))


def build_cycle(
    volumes: list[float],
    rpm: float,
    p_int: float,
    p_exh: float,
    kappa_comp: float,
    kappa_exp: float,
    fired_cyls: set[int],
    knock: dict[int, float],
    q_fired_j: float,
    soc_atdc: float,
    burn_dur_cad: float,
    kappa_fired: float,
    noise_bar: float,
    drift_bar: float,
    rng: random.Random,
) -> tuple[list[list[float]], dict, list[list[float]]]:
    """One raw 9x7200 block, its per-cylinder truth record, and the 6x7200
    phased single-cylinder frames (for feeding APC_HRL directly)."""
    raw = [[0.0] * N_SAMPLES for _ in range(len(ROWS))]
    truth: dict = {"cylinders": {}}

    cyl_frames = []
    for cyl in range(1, 7):
        fired = cyl in fired_cyls
        clean = cylinder_trace(
            volumes, p_int, p_exh, kappa_comp, kappa_exp,
            fired=fired, q_fired_j=q_fired_j, soc_atdc=soc_atdc,
            burn_dur_cad=burn_dur_cad, kappa_fired=kappa_fired,
        )
        rec = {"fired": fired, **metrics(clean, volumes)}
        if fired:
            rec["ca50_atdc"] = round(ca50_truth(soc_atdc, burn_dur_cad), 2)
        if cyl in knock:
            clean = add_knock(clean, knock[cyl], rpm)
            rec["knock_amp_bar"] = knock[cyl]
        truth["cylinders"][str(cyl)] = rec
        cyl_frames.append(clean)

    for cyl in range(1, 7):
        offset = CYL_OFFSETS[cyl - 1]
        frame = cyl_frames[cyl - 1]
        off0 = rng.uniform(-drift_bar, drift_bar)  # piezo offset; pegging must remove it
        row = raw[cyl - 1]
        for i in range(N_SAMPLES):
            row[i] = frame[(i - offset) % N_SAMPLES] + off0 + rng.gauss(0.0, noise_bar)

    # Prechamber = attenuated, slightly lagged cyl 6 (small PrechamberPeakDiff).
    off6 = CYL_OFFSETS[5]
    frame6 = cyl_frames[5]
    for i in range(N_SAMPLES):
        raw[6][i] = 0.97 * frame6[(i - off6 - 5) % N_SAMPLES] + rng.gauss(0.0, noise_bar)
    # System / exhaust: near-flat with mild ripple.
    for i in range(N_SAMPLES):
        ripple = 0.02 * math.sin(2 * math.pi * 6 * i / N_SAMPLES)
        raw[7][i] = p_int + ripple + rng.gauss(0.0, noise_bar)
        raw[8][i] = p_exh + ripple + rng.gauss(0.0, noise_bar)
    # Phased per-cylinder frames (each in its OWN -360..+359.9 CADATDC frame,
    # firing TDC at sample 3600): feed these straight into APC_HRL for the
    # globals-free desktop SIL-0 harness — no PPhaseCorrection needed. Rows =
    # cyl 1..6, cols = 7200 samples, bar. These match `truth.json` exactly.
    phased = [list(cyl_frames[c]) for c in range(6)]
    return raw, truth, phased


def write_cycle_csv(path: Path, rows: list[list[float]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(",".join(f"{v:.5f}" for v in row))
            fh.write("\n")


def parse_pairs(specs: list[str], what: str) -> dict[tuple[int, int], float]:
    """Parse cyl:cycle[:amp] CLI specs -> {(cyl, cycle): amp}."""
    out: dict[tuple[int, int], float] = {}
    for s in specs:
        parts = s.split(":")
        if len(parts) not in (2, 3):
            raise SystemExit(f"bad --{what} spec {s!r} (want cyl:cycle[:amp])")
        cyl, cycle = int(parts[0]), int(parts[1])
        if not 1 <= cyl <= 6:
            raise SystemExit(f"--{what} cylinder must be 1..6, got {cyl}")
        out[(cyl, cycle)] = float(parts[2]) if len(parts) == 3 else 0.0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic 9049 CAS pressure cycles + ground truth")
    ap.add_argument("out_dir", help="output directory (created if missing)")
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--mode", choices=["motored", "fired", "mixed"], default="motored",
                    help="mixed = motored until --fire-from, fired after")
    ap.add_argument("--fire-from", type=int, default=5, help="first fired cycle in mixed mode (1-based)")
    ap.add_argument("--rpm", type=float, default=900.0)
    ap.add_argument("--p-int", type=float, default=2.9, help="intake/system pressure [bar]")
    ap.add_argument("--p-exh", type=float, default=3.0, help="exhaust backpressure [bar]")
    ap.add_argument("--kappa-comp", type=float, default=1.55, help="motored compression kappa (argon-rich placeholder)")
    ap.add_argument("--kappa-exp", type=float, default=1.62, help="motored expansion kappa (> comp = heat loss)")
    ap.add_argument("--kappa-fired", type=float, default=1.45)
    ap.add_argument("--q-fired", type=float, default=3000.0, help="heat released per fired cycle [J]")
    ap.add_argument("--soc", type=float, default=-8.0, help="start of combustion [CADATDC]")
    ap.add_argument("--burn-dur", type=float, default=45.0, help="Wiebe 0-100%% duration [CAD]")
    ap.add_argument("--bore", type=float, default=Geometry.bore_m)
    ap.add_argument("--stroke", type=float, default=Geometry.stroke_m)
    ap.add_argument("--conrod", type=float, default=Geometry.conrod_m)
    ap.add_argument("--cr", type=float, default=Geometry.compression_ratio)
    ap.add_argument("--pin-offset", type=float, default=Geometry.pin_offset_m)
    ap.add_argument("--noise", type=float, default=0.01, help="gaussian noise sigma [bar]")
    ap.add_argument("--drift", type=float, default=0.2,
                    help="max per-cycle piezo offset [bar] (exercises pegging)")
    ap.add_argument("--misfire", action="append", default=[], metavar="CYL:CYCLE",
                    help="motored cycle for one cylinder (repeatable)")
    ap.add_argument("--knock", action="append", default=[], metavar="CYL:CYCLE:AMP_BAR",
                    help="inject knock oscillation (repeatable)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    geom = Geometry(args.bore, args.stroke, args.conrod, args.cr, args.pin_offset)
    volumes = volume_curve(geom)
    rng = random.Random(args.seed)
    misfires = parse_pairs(args.misfire, "misfire")
    knocks = parse_pairs(args.knock, "knock")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    truth_all: dict = {
        "params": {**vars(args), "geometry": asdict(geom)},
        "row_map": ROWS,
        "frame": "raw rows share one engine-absolute frame; cyl k TDC at sample "
                 f"(3600 + offset) %% 7200, offsets {CYL_OFFSETS} (cyl 1..6)",
        "cycles": {},
    }

    for cycle in range(1, args.cycles + 1):
        if args.mode == "motored":
            fired_cyls: set[int] = set()
        elif args.mode == "fired":
            fired_cyls = set(range(1, 7))
        else:
            fired_cyls = set(range(1, 7)) if cycle >= args.fire_from else set()
        fired_cyls -= {cyl for (cyl, cyc) in misfires if cyc == cycle}
        knock_now = {cyl: amp for (cyl, cyc), amp in knocks.items() if cyc == cycle}

        raw, truth, phased = build_cycle(
            volumes, args.rpm, args.p_int, args.p_exh, args.kappa_comp,
            args.kappa_exp, fired_cyls, knock_now, args.q_fired, args.soc,
            args.burn_dur, args.kappa_fired, args.noise, args.drift, rng,
        )
        write_cycle_csv(out / f"cycle_{cycle:04d}.csv", raw)          # 9x7200 raw (full CAS chain)
        write_cycle_csv(out / f"cycle_{cycle:04d}_phased.csv", phased)  # 6x7200 phased (feed APC_HRL)
        truth_all["cycles"][str(cycle)] = truth

    (out / "truth.json").write_text(json.dumps(truth_all, indent=2) + "\n", encoding="utf-8")
    per_cycle_ms = 60000.0 / args.rpm * 2.0
    print(f"wrote {args.cycles} cycles to {out}/:")
    print(f"  cycle_NNNN.csv        = 9x{N_SAMPLES} raw   (Pcyl1-6, Ppre, Psyst, Pexh) for the full CAS chain")
    print(f"  cycle_NNNN_phased.csv = 6x{N_SAMPLES} phased (cyl 1-6, TDC at sample 3600) — feed straight to APC_HRL")
    print(f"  truth.json            = ground-truth IMEP/CA50/Pmax per cycle per cylinder")
    print(f"cycle pacing at {args.rpm:.0f} rpm: {per_cycle_ms:.1f} ms/cycle (for a LabVIEW sim-read Wait)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
