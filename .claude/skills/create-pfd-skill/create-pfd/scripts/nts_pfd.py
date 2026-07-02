"""
Shared PFD-drawing style and toolkit for NTS process flow diagrams.

Mirrors the role of plot_style.py for plots: import it at the top of every
PFD script and let it enforce the house conventions (symbol library, stream
colour classes, tag numbering, orthogonal routing, vectorised SVG output) and
run an automatic quality-control pass before saving.

    from nts_pfd import PFD, STREAMS

Symbols are the real Visio stencil masters, extracted to tight-viewBox SVG with
named ports (nozzles) so pipes attach at true connection points.

Quality control (runs automatically in .save()):
  * pennant labels are sized to their text          -> no truncation / overflow
  * pipes to a pennant attach on the facing side     -> no line crossing text
  * the canvas is grown to contain every element     -> nothing clipped at edges
  * overlapping tag labels are nudged apart
  * remaining overlaps (symbol/symbol, line/text) are reported, not hidden
"""

import os, re, json

_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS = os.path.normpath(os.path.join(_DIR, "..", "assets", "symbols"))

STREAMS = {
    "process":      "#1a1a1a",
    "oxygen":       "#1f6fb2",
    "condenser":    "#2e7d32",
    "feed_precool": "#7b3fb0",
    "water":        "#c0392b",
}
STREAM_LABEL = {
    "process": "PROCESS (Ar/CO2)", "oxygen": "OXYGEN",
    "condenser": "CONDENSER COOLANT LOOP", "feed_precool": "FEED-PRECOOL COOLANT LOOP",
    "water": "WATER UTILITY",
}
FONT = "TeX Gyre Heros, Helvetica, Arial, sans-serif"


# --- text measurement -------------------------------------------------------
def _font(size):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, int(round(size)))
    return ImageFont.load_default()

def text_width(s, size):
    try:
        return _font(size).getlength(str(s))
    except Exception:
        return 0.62 * size * len(str(s))


def _load_library():
    meta = json.load(open(os.path.join(_ASSETS, "symbols.json")))
    for key, m in meta.items():
        svg = open(os.path.join(_ASSETS, m["file"])).read()
        root = svg[svg.find("<svg"):svg.find(">", svg.find("<svg")) + 1]
        m["_ns"] = " ".join(re.findall(r'xmlns:[\w-]+="[^"]*"', root))
        m["_inner"] = svg[svg.find(">", svg.find("<svg")) + 1: svg.rfind("</svg>")]
        if "viewBox" not in m:
            m["viewBox"] = [float(v) for v in re.search(r'viewBox="([^"]+)"', root).group(1).split()]
    return meta

LIBRARY = _load_library()


# --- geometry helpers -------------------------------------------------------
class Port(tuple):
    """A coordinate that also remembers which way a pipe leaves it."""
    def __new__(cls, xy, d):
        self = super().__new__(cls, xy); self.d = d; return self


def _seg_rect(p, q, rect, pad=1.0):
    x0, y0, x1, y1 = rect[0]-pad, rect[1]-pad, rect[2]+pad, rect[3]+pad
    (ax, ay), (bx, by) = p, q
    if max(ax, bx) < x0 or min(ax, bx) > x1 or max(ay, by) < y0 or min(ay, by) > y1:
        return False
    if abs(ay - by) < 0.5:
        return y0 <= ay <= y1
    if abs(ax - bx) < 0.5:
        return x0 <= ax <= x1
    return True


def _overlap(a, b, pad=0):
    return not (a[2]+pad <= b[0] or b[2]+pad <= a[0] or a[3]+pad <= b[1] or b[3]+pad <= a[1])


class _Node:
    def __init__(self, key, x, y, w, h, tag):
        self.key, self.x, self.y, self.w, self.h, self.tag = key, x, y, w, h, tag
        self.ports = LIBRARY[key]["ports"]
    def bbox(self): return (self.x, self.y, self.x+self.w, self.y+self.h)
    def port(self, name):
        fx, fy = self.ports[name]
        d = "L" if fx <= .02 else "R" if fx >= .98 else "U" if fy <= .02 else "D"
        return Port((self.x + fx*self.w, self.y + fy*self.h), d)


class _Pennant:
    def __init__(self, x, y, w, h, text, chevron, color):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text, self.chevron, self.color = text, chevron, color
    def bbox(self): return (self.x, self.y, self.x+self.w, self.y+self.h)
    def side(self, which):
        return Port((self.x if which == "left" else self.x+self.w, self.y+self.h/2),
                    "L" if which == "left" else "R")


class PFD:
    def __init__(self, width, height, title=None, subtitle=None, margin=16):
        self.W, self.H, self.margin = width, height, margin
        self.title, self.subtitle = title, subtitle
        self._symbols, self._pennants, self._texts = [], [], []
        self._conns, self._legends = [], []
        self._tags = {}

    # -- placement ----------------------------------------------------------
    def add(self, key, x, y, h, tag=None, flip=False):
        m = LIBRARY[key]; w = h * m["aspect"]
        if tag is None:
            p = m["tag_prefix"]; self._tags[p] = self._tags.get(p, 100) + 1
            tag = f"{p}-{self._tags[p]}"
        node = _Node(key, x, y, w, h, tag)
        self._symbols.append((node, flip))
        if tag:
            if m["aspect"] < 0.7:   # tall (columns, vessels): tag beside the base, clear of nozzles
                self.text(x + w + 8, y + h - 6, tag, weight="bold", anchor="start", role="tag")
            else:                   # normal/wide: centered below
                self.text(x + w/2, y + h + 15, tag, weight="bold", anchor="middle", role="tag")
        return node

    def pennant(self, x, y, text, stream="process", chevron="right", h=26):
        pen = _Pennant(x, y, 0, h, text, chevron, STREAMS[stream])
        self._pennants.append(pen)
        return pen

    def connect(self, a, b, stream="process", width=2.0, arrow=True):
        # arrow: draw a flow arrowhead at the b (downstream) end. Suppressed
        # automatically when b is a pennant (the pennant chevron shows direction).
        self._conns.append(dict(a=a, b=b, stream=stream, width=width, arrow=arrow))

    def text(self, x, y, t, size=12, weight="normal", anchor="middle",
             color="#1a1a1a", role="annotation"):
        self._texts.append(dict(x=x, y=y, t=str(t), size=size, weight=weight,
                                anchor=anchor, color=color, role=role))

    def legend(self, x, y, streams):
        self._legends.append(dict(x=x, y=y, streams=list(streams)))

    # ===================================================================
    # QUALITY CONTROL
    # ===================================================================
    def validate(self, fix=True, verbose=True):
        issues, fixes = [], []
        PAD, CHEV = 10, 12

        # 1) size pennants to their text
        for p in self._pennants:
            need = text_width(p.text, 11.5) + 2*PAD + CHEV
            if fix:
                if p.w < need:
                    p.w = max(96, need)
            elif p.w < need - 0.5:
                issues.append(f"pennant '{p.text}' text overflows")

        # resolve endpoints; choose facing side for pennants
        def cx(e):
            return (e.x + e.w/2) if isinstance(e, _Pennant) else e[0]
        used_side = 0
        for c in self._conns:
            for end in ("a", "b"):
                e = c[end]
                if isinstance(e, _Pennant):
                    ox = cx(c["b" if end == "a" else "a"])
                    which = "left" if ox < e.x + e.w/2 else "right"
                    c[end+"_pt"] = e.side(which); used_side += 1
                else:
                    c[end+"_pt"] = e
        if used_side:
            fixes.append(f"selected facing connection side for {used_side} pennant link(s)")
        for c in self._conns:
            c["route"] = self._route(c["a_pt"], c["b_pt"])

        # text bboxes
        def tbbox(t):
            w = text_width(t["t"], t["size"]); h = t["size"]*1.2
            x = t["x"] - (w if t["anchor"] == "end" else w/2 if t["anchor"] == "middle" else 0)
            return (x, t["y"]-h*0.8, x+w, t["y"]+h*0.2)
        text_boxes = [(t, tbbox(t)) for t in self._texts]
        pen_text_boxes = []
        for p in self._pennants:
            tw = text_width(p.text, 11.5)
            bx0 = p.x + (10 if p.chevron == "right" else p.w-10-tw)
            pen_text_boxes.append((p, (bx0, p.y+p.h/2-7, bx0+tw, p.y+p.h/2+7)))

        # 2) line crosses text?
        for c in self._conns:
            r = c["route"]
            for owner, box in text_boxes + pen_text_boxes:
                hit = any(_seg_rect(r[i], r[i+1], box, pad=2) for i in range(len(r)-1))
                if hit:
                    txt = owner.text if isinstance(owner, _Pennant) else owner["t"]
                    issues.append(f"pipe crosses text label '{txt}'")
                    break

        # 3) overlapping tag labels -> nudge
        if fix:
            tags = [t for t in self._texts if t["role"] == "tag"]
            for i in range(len(tags)):
                for j in range(i+1, len(tags)):
                    if _overlap(tbbox(tags[i]), tbbox(tags[j]), pad=2):
                        tags[j]["y"] += tags[j]["size"]*1.3
                        fixes.append("nudged overlapping tag label")

        # 3b) any label still crossed by a pipe -> nudge clear (backstop)
        if fix:
            for t in [x for x in self._texts if x["role"] in ("tag", "annotation")]:
                for _ in range(4):
                    box = tbbox(t); hit = None
                    for c in self._conns:
                        r = c["route"]
                        for i in range(len(r)-1):
                            if _seg_rect(r[i], r[i+1], box, pad=2):
                                hit = (r[i], r[i+1]); break
                        if hit:
                            break
                    if not hit:
                        break
                    (ax, ay), (bx, by) = hit
                    if abs(ax - bx) < 0.5:          # vertical pipe -> drop label below it
                        t["y"] = max(ay, by) + t["size"]*1.1 + 5
                    else:                           # horizontal pipe -> lift label above it
                        t["y"] = min(ay, by) - 7
                    fixes.append(f"nudged label '{t['t']}' clear of a pipe")

        # 4) symbol/symbol overlap -> report
        syms = [n for n, _ in self._symbols]
        for i in range(len(syms)):
            for j in range(i+1, len(syms)):
                if _overlap(syms[i].bbox(), syms[j].bbox()):
                    issues.append(f"symbols overlap: {syms[i].tag} & {syms[j].tag}")

        # 5) grow canvas to contain everything
        if fix:
            xs, ys = [], []
            for n, _ in self._symbols:
                b = n.bbox(); xs += [b[0], b[2]]; ys += [b[1], b[3]]
            for p in self._pennants:
                b = p.bbox(); xs += [b[0], b[2]]; ys += [b[1], b[3]]
            for _, b in text_boxes:
                xs += [b[0], b[2]]; ys += [b[1], b[3]]
            for L in self._legends:
                xs += [L["x"], L["x"]+270]; ys.append(L["y"] + len(L["streams"])*20)
            for c in self._conns:
                for pt in c["route"]:
                    xs.append(pt[0]); ys.append(pt[1])
            if xs:
                nw, nh = max(xs)+self.margin, max(ys)+self.margin
                if nw > self.W or nh > self.H:
                    old = (self.W, self.H)
                    self.W, self.H = max(self.W, nw), max(self.H, nh)
                    fixes.append(f"grew canvas {old[0]:.0f}x{old[1]:.0f} -> {self.W:.0f}x{self.H:.0f}")

        if verbose:
            print(f"QC: {len(syms)} components, {len(self._pennants)} pennants, "
                  f"{len(self._conns)} connectors, {len(self._texts)} labels")
            for f in fixes:
                print(f"QC fix: {f}")
            if issues:
                for it in issues:
                    print(f"QC WARNING (unresolved): {it}")
            else:
                print("QC: no unresolved overlaps / truncation / clipping")
        return issues

    # -- routing ------------------------------------------------------------
    def _route(self, a, b, stub=14):
        (x1, y1), (x2, y2) = a, b
        sd = getattr(a, "d", None) or self._guess(a, b)
        ed = getattr(b, "d", None) or self._guess(b, a)
        sp = self._step((x1, y1), sd, stub)
        ep = self._step((x2, y2), ed, stub)
        pts = [(x1, y1), sp] + self._manhattan(sp, sd, ep, ed) + [ep, (x2, y2)]
        clean = [pts[0]]
        for pt in pts[1:]:
            if abs(pt[0]-clean[-1][0]) > .5 or abs(pt[1]-clean[-1][1]) > .5:
                clean.append(pt)
        return clean

    def _manhattan(self, sp, sd, ep, ed):
        hs, he = sd in ("L", "R"), ed in ("L", "R")
        if hs and he:
            mx = (sp[0]+ep[0])/2; return [(mx, sp[1]), (mx, ep[1])]
        if hs and not he:
            return [(ep[0], sp[1])]
        if not hs and he:
            return [(sp[0], ep[1])]
        my = (sp[1]+ep[1])/2; return [(sp[0], my), (ep[0], my)]

    @staticmethod
    def _step(p, d, s):
        return (p[0] + {"L": -s, "R": s}.get(d, 0), p[1] + {"U": -s, "D": s}.get(d, 0))
    @staticmethod
    def _guess(a, b):
        return ("R" if b[0] >= a[0] else "L") if abs(b[0]-a[0]) >= abs(b[1]-a[1]) \
            else ("D" if b[1] >= a[1] else "U")

    @staticmethod
    def _arrowhead(p_prev, p_end, color, size=9):
        """Filled flow arrowhead, tip at p_end, pointing along p_prev -> p_end."""
        dx, dy = p_end[0]-p_prev[0], p_end[1]-p_prev[1]
        d = (dx*dx + dy*dy) ** 0.5 or 1.0
        ux, uy = dx/d, dy/d                 # unit vector along flow
        px, py = -uy, ux                    # perpendicular
        bx, by = p_end[0]-ux*size, p_end[1]-uy*size
        w = size*0.46
        return (f'<polygon points="{p_end[0]:.1f},{p_end[1]:.1f} '
                f'{bx+px*w:.1f},{by+py*w:.1f} {bx-px*w:.1f},{by-py*w:.1f}" '
                f'fill="{color}"/>')

    # -- render -------------------------------------------------------------
    def svg(self):
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
               f'viewBox="0 0 {self.W:.0f} {self.H:.0f}"><rect width="{self.W:.0f}" '
               f'height="{self.H:.0f}" fill="white"/>']
        if self.title:
            out.append(f'<text x="{self.margin}" y="34" font-family="{FONT}" font-size="16" '
                       f'font-weight="bold" fill="#1a1a1a">{self.title}</text>')
        if self.subtitle:
            out.append(f'<text x="{self.margin}" y="54" font-family="{FONT}" font-size="11" '
                       f'fill="#666">{self.subtitle}</text>')
        for c in self._conns:
            r = c.get("route") or self._route(c.get("a_pt", c["a"]), c.get("b_pt", c["b"]))
            path = " ".join(f"{x:.1f},{y:.1f}" for x, y in r)
            col = STREAMS[c["stream"]]
            out.append(f'<polyline points="{path}" fill="none" stroke="{col}" '
                       f'stroke-width="{c["width"]}" stroke-linejoin="round" stroke-linecap="round"/>')
            if c.get("arrow", True) and not isinstance(c["b"], _Pennant) and len(r) >= 2:
                out.append(self._arrowhead(r[-2], r[-1], col))
        for n, flip in self._symbols:
            m = LIBRARY[n.key]; vb = m["viewBox"]
            sx = -1 if flip else 1; tx = (n.x+n.w) if flip else n.x
            out.append(f'<g transform="translate({tx:.1f},{n.y:.1f}) scale({sx},1)">'
                       f'<svg width="{n.w:.1f}" height="{n.h:.1f}" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}" '
                       f'{m["_ns"]} preserveAspectRatio="none" overflow="visible">{m["_inner"]}</svg></g>')
        for p in self._pennants:
            x, y, w, h = p.x, p.y, p.w, p.h
            if p.chevron == "right":
                pts = f"{x},{y} {x+w-12},{y} {x+w},{y+h/2} {x+w-12},{y+h} {x},{y+h}"
                tx, ta = x+10, "start"
            else:
                pts = f"{x+w},{y} {x+12},{y} {x},{y+h/2} {x+12},{y+h} {x+w},{y+h}"
                tx, ta = x+w-10, "end"
            out.append(f'<polygon points="{pts}" fill="white" stroke="{p.color}" stroke-width="2"/>')
            out.append(f'<text x="{tx:.1f}" y="{y+h/2+4:.1f}" font-family="{FONT}" font-size="11.5" '
                       f'text-anchor="{ta}" fill="{p.color}">{p.text}</text>')
        for t in self._texts:
            out.append(f'<text x="{t["x"]:.1f}" y="{t["y"]:.1f}" font-family="{FONT}" '
                       f'font-size="{t["size"]}" font-weight="{t["weight"]}" '
                       f'text-anchor="{t["anchor"]}" fill="{t["color"]}">{t["t"]}</text>')
        for L in self._legends:
            for i, s in enumerate(L["streams"]):
                yy = L["y"] + i*20
                out.append(f'<line x1="{L["x"]}" y1="{yy}" x2="{L["x"]+34}" y2="{yy}" '
                           f'stroke="{STREAMS[s]}" stroke-width="2.4"/>')
                out.append(f'<text x="{L["x"]+44}" y="{yy+4}" font-family="{FONT}" font-size="10" '
                           f'text-anchor="start" fill="#1a1a1a">{STREAM_LABEL[s]}</text>')
        out.append("</svg>")
        return "".join(out)

    def save(self, path, scale=2, qc=True):
        if qc:
            self.validate(fix=True, verbose=True)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        base = path[:-4] if path.lower().endswith(".png") else path
        svg_path, png_path = base + ".svg", base + ".png"
        src = self.svg()
        open(svg_path, "w").write(src); print(f"Saved {svg_path}")
        try:
            import cairosvg
            cairosvg.svg2png(bytestring=src.encode(), write_to=png_path,
                             output_width=int(self.W*scale), background_color="white")
            print(f"Saved {png_path}")
        except Exception as e:
            print(f"(PNG skipped: {e})")
        return svg_path
