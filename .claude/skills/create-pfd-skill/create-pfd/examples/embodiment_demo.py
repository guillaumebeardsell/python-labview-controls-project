"""Worked example: a GSU-permeate-to-column train, built with the create-pfd skill.

Pennants are passed straight to connect(); the QC pass in save() sizes them to
their text, attaches pipes on the facing side, and grows the canvas to fit.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from nts_pfd import PFD, STREAMS

OUT = sys.argv[1] if len(sys.argv) > 1 else "output/embodiment_demo.png"

pfd = PFD(1020, 600,
          title="Demo PFD — built through the create-pfd skill",
          subtitle="symbols = real Visio masters · named ports · orthogonal routing · auto-QC")
y = 300
gsu = pfd.pennant(20, y - 13, "GSU PERMEATE")
c   = pfd.add("compressor", 150, y - 35, 70)      # C-101
ve  = pfd.add("vessel", 300, y - 35, 70)          # VE-101
e   = pfd.add("heat_exchanger", 430, y - 35, 70)  # E-101
col = pfd.add("column", 660, 140, 300)            # T-101
pmp = pfd.add("pump", 560, 470, 70)               # P-101

pfd.connect(gsu, c.port("in"))
pfd.connect(c.port("out"), ve.port("in"))
pfd.connect(ve.port("out"), e.port("in"))
pfd.connect(e.port("out"), col.port("feed"))
pfd.connect((e.port("top")[0], 150), e.port("top"), stream="condenser")
pfd.text(e.port("top")[0], 145, "COOLANT", size=10, color=STREAMS["condenser"])

ovh = pfd.pennant(860, 90, "OVHD VAPOR")
pfd.connect(col.port("top"), ovh)
pfd.connect(col.port("bottom"), pmp.port("out"))
co2 = pfd.pennant(360, 470 - 13, "LIQUID CO2")
pfd.connect(pmp.port("in"), co2)

pfd.legend(20, 590, ["process", "condenser", "oxygen", "feed_precool", "water"])
pfd.save(OUT)
