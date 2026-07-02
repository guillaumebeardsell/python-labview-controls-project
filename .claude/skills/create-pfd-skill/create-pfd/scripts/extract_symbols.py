"""
Extract Visio stencil masters into tight-viewBox SVG symbols for the PFD library.

Usage:
    python extract_symbols.py NTS_COMPONENTS.vssx

Requires LibreOffice (`soffice` on PATH) — it carries the Visio import filter
(libvisio) that resolves the master geometry. Edit SYMBOL_SPEC below to choose
which masters to extract, their tag prefix, and their named ports.

Caveat: Visio *group* masters (e.g. the dedicated "Tray column") do not render
through libvisio when referenced from a bare master instance. For those, either
export the single master to SVG from Visio directly (drop it on a page, then
File > Export > SVG) and drop the file in assets/symbols/, or use a composite
(see assets/symbols/column.svg).
"""
import os, re, sys, json, zipfile, subprocess, tempfile, io

ASSETS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "symbols"))

# key -> (master_NameU_or_ID, tag_prefix, {port: [fx, fy]})
SYMBOL_SPEC = {
    "heat_exchanger":    ("HEAT EXCHANGER",      "E",  {"in":[0,.5], "out":[1,.5], "top":[.5,0], "bottom":[.5,1]}),
    "shell_tube_hx":     ("SHELL AND TUBE HEAT EXCHANGER", "E", {"in":[0,.5], "out":[1,.5]}),
    "plate_hx":          ("PLATE HEAT EXCHANGER", "E",  {"in":[0,.5], "out":[1,.5]}),
    "pump":              ("PUMP",                 "P",  {"in":[0,.5], "out":[1,.5]}),
    "compressor":        ("COMPRESSOR",           "C",  {"in":[0,.5], "out":[1,.5]}),
    "vessel":            ("VESSEL",               "VE", {"top":[.5,0], "bottom":[.5,1], "in":[0,.5], "out":[1,.5]}),
    "rounded_vessel":    ("ROUNDED/ANGLED VESSEL","VE", {"top":[.5,0], "bottom":[.5,1], "in":[0,.5], "out":[1,.5]}),
    "membrane_permeate": ("MEMBRANE 1 PERMEATE",  "M",  {"in":[0,.5], "out":[1,.5], "permeate":[.5,1]}),
    "general_valve":     ("GENERAL VALVE",        "V",  {"in":[0,.5], "out":[1,.5]}),
    "globe_valve":       ("GLOBE VALVE",          "V",  {"in":[0,.5], "out":[1,.5]}),
    "check_valve":       ("CHECK VALVE",          "V",  {"in":[0,.5], "out":[1,.5]}),
}


def masters_index(parts):
    mx = parts["visio/masters/masters.xml"].decode("utf-8")
    rels = parts["visio/masters/_rels/masters.xml.rels"].decode("utf-8")
    relmap = dict(re.findall(r'Id="(rId\d+)"\s+Type="[^"]*master"\s+Target="([^"]+)"', rels))
    idx = {}
    for block in re.split(r"(?=<Master\b)", mx):
        mid = re.search(r"<Master\b[^>]*\bID='(\d+)'", block)
        if not mid:
            continue
        name = re.search(r"NameU='([^']*)'", block) or re.search(r"Name='([^']*)'", block)
        rel = re.search(r"<Rel\b[^>]*r:id='(rId\d+)'", block)
        if not rel:
            continue
        idx[int(mid.group(1))] = {
            "name": name.group(1) if name else "?",
            "file": "visio/masters/" + relmap[rel.group(1)],
        }
    return idx


def resolve_id(idx, ref):
    if isinstance(ref, int):
        return ref
    for mid, m in idx.items():
        if m["name"].upper() == ref.upper():
            return mid
    raise KeyError(f"master not found: {ref}")


def native_size(parts, mfile):
    mx = parts[mfile].decode("utf-8")
    w = re.search(r"<Cell N='Width' V='([0-9.eE+-]+)'", mx)
    h = re.search(r"<Cell N='Height' V='([0-9.eE+-]+)'", mx)
    return (float(w.group(1)) if w else 0.7, float(h.group(1)) if h else 0.7)


def render_master_svg(pkg, mid, out_svg, margin=0.05):
    z = zipfile.ZipFile(pkg); parts = {n: z.read(n) for n in z.namelist()}
    idx = masters_index(parts); m = idx[mid]; W, H = native_size(parts, m["file"])
    PW, PH = W + 2 * margin, H + 2 * margin
    shape = (f"<Shape ID='1' Type='Shape' Master='{mid}'>"
             f"<Cell N='PinX' V='{PW/2:.4f}'/><Cell N='PinY' V='{PH/2:.4f}'/>"
             f"<Cell N='Width' V='{W:.4f}'/><Cell N='Height' V='{H:.4f}'/>"
             f"<Cell N='LocPinX' V='{W/2:.4f}'/><Cell N='LocPinY' V='{H/2:.4f}'/><Text></Text></Shape>")
    parts["visio/pages/page1.xml"] = (
        "<?xml version='1.0' encoding='utf-8' ?>\r\n<PageContents "
        "xmlns='http://schemas.microsoft.com/office/visio/2012/main' "
        "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' "
        "xml:space='preserve'><Shapes>" + shape + "</Shapes></PageContents>").encode()
    parts["visio/pages/pages.xml"] = (
        "<?xml version='1.0' encoding='utf-8' ?>\r\n<Pages "
        "xmlns='http://schemas.microsoft.com/office/visio/2012/main' "
        "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' "
        f"xml:space='preserve'><Page ID='0' NameU='P' Name='P'><PageSheet>"
        f"<Cell N='PageWidth' V='{PW:.4f}'/><Cell N='PageHeight' V='{PH:.4f}'/></PageSheet>"
        "<Rel r:id='rId1'/></Page></Pages>").encode()
    parts["visio/pages/_rels/pages.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" '
        'Target="page1.xml"/></Relationships>').encode()
    for n in list(parts):
        if re.match(r"visio/pages/page\d+\.xml$", n) and n != "visio/pages/page1.xml":
            del parts[n]
        if re.match(r"visio/pages/_rels/page\d+\.xml\.rels$", n) and not n.endswith("pages.xml.rels"):
            del parts[n]
    ct = parts["[Content_Types].xml"].decode()
    ct = re.sub(r'<Override PartName="/visio/pages/page\d+\.xml"[^>]*/>', "", ct)
    ct = ct.replace('pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>',
                    'pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
                    '<Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>')
    parts["[Content_Types].xml"] = ct.encode()
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, f"m{mid}.vsdx")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
            for n, b in parts.items():
                zo.writestr(n, b)
        subprocess.run(["soffice", "--headless", "--convert-to", "svg", "--outdir", td, tmp],
                       check=True, capture_output=True, timeout=120)
        produced = tmp.replace(".vsdx", ".svg")
        os.replace(produced, out_svg)
    return out_svg


def tighten(out_svg):
    import cairosvg
    from PIL import Image
    s = open(out_svg).read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', s).group(1).split()]
    scale = 600.0 / vb[2]
    png = cairosvg.svg2png(url=out_svg, output_width=int(vb[2] * scale), background_color="white")
    im = Image.open(io.BytesIO(png)).convert("L")
    bb = im.point(lambda p: 0 if p > 248 else 255).getbbox()
    if not bb:
        return vb
    x0, y0, x1, y1 = [c / scale for c in bb]
    pad = vb[2] * 0.005
    tb = [x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad]
    s = re.sub(r'(<svg[^>]*\sviewBox=")[^"]+(")',
               lambda m: f"{m.group(1)}{tb[0]:.1f} {tb[1]:.1f} {tb[2]:.1f} {tb[3]:.1f}{m.group(2)}", s, count=1)
    s = re.sub(r'(<svg[^>]*?)\swidth="[^"]*"', r"\1", s, count=1)
    s = re.sub(r'(<svg[^>]*?)\sheight="[^"]*"', r"\1", s, count=1)
    open(out_svg, "w").write(s)
    return tb


def main(pkg):
    os.makedirs(ASSETS, exist_ok=True)
    z = zipfile.ZipFile(pkg); idx = masters_index({n: z.read(n) for n in z.namelist()})
    meta = {}
    jpath = os.path.join(ASSETS, "symbols.json")
    if os.path.exists(jpath):
        meta = json.load(open(jpath))
    for key, (ref, prefix, ports) in SYMBOL_SPEC.items():
        mid = resolve_id(idx, ref)
        out = os.path.join(ASSETS, f"{key}.svg")
        render_master_svg(pkg, mid, out)
        tb = tighten(out)
        meta[key] = {"file": f"{key}.svg", "viewBox": [round(v, 1) for v in tb],
                     "aspect": round(tb[2] / tb[3], 3), "tag_prefix": prefix, "ports": ports}
        print(f"  {key:18} <- {ref:32} tag={prefix}")
    json.dump(meta, open(jpath, "w"), indent=2)
    print(f"Wrote {len(meta)} symbols to {jpath}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1])
