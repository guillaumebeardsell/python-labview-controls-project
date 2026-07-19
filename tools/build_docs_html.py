"""Generate the styled HTML documentation site from the repo's markdown files.

    python tools/build_docs_html.py            # writes docs-site/

The markdown files remain the single source of truth — the HTML is a build
artifact, regenerated in one command, so the two can never drift (re-run after
editing any .md). Output mirrors the repo layout under docs-site/ so relative
links survive the .md → .html rewrite. Mermaid diagrams render client-side via
CDN when online, with the source shown as a fallback when offline.

Requires: pip install markdown  (pure-python, no other deps).
"""

from __future__ import annotations

import datetime
import html as html_mod
import re
import shutil
import sys
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover
    raise SystemExit("pip install markdown  (needed by tools/build_docs_html.py)")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs-site"

# Every markdown file that becomes a page (repo-relative).
SOURCES = (
    sorted(p.relative_to(ROOT) for p in (ROOT / "docs").rglob("*.md"))
    + [Path("README.md"), Path("CLAUDE.md"), Path("tools/README.md"),
       Path("original-labview-codebase/MONARCH-CODEBASE/README.md")]
)

# Index groups: (heading, blurb, [repo-relative paths]) — order = page order.
GROUPS = [
    ("Start here", "Orientation, status, and how to continue the project.", [
        "README.md", "docs/migration-plan.md", "docs/handoff.md",
        "docs/session-handoff-2026-07-11.md", "CLAUDE.md",
    ]),
    ("As-built references", "How the LabVIEW system actually works — verified against exports and live bench evidence.", [
        "original-labview-codebase/MONARCH-CODEBASE/README.md",
        "docs/command-path-asbuilt.md", "docs/9056-warning-policy-asbuilt.md",
        "docs/migration-seam.md", "docs/9049-openloop-audit.md",
    ]),
    ("Contracts & protocol", "The Python ⇄ LabVIEW wire contract and its verification workflow.", [
        "docs/icd.md", "docs/monarch-control-settings.md",
        "docs/monarch-telemetry.md", "docs/monarch-flatten-diff.md",
    ]),
    ("SIL & commissioning procedures", "Click-level bench procedures, decisions, and hardening builds.", [
        "docs/sil0-scope-of-work.md", "docs/sil1-scope-of-work.md",
        "docs/hb-hardening-clicklevel.md", "docs/engine-only-9056-tradeoff.md",
        "docs/deployed-bringup.md", "docs/crio-file-access.md",
    ]),
    ("Phase instructions", "One file per migration phase (A–E).", [
        "docs/phases/phase-a-shadow-brain.md", "docs/phases/phase-b-command-path.md",
        "docs/phases/phase-c-bench-command.md", "docs/phases/phase-d-sequencing.md",
        "docs/phases/phase-e-commissioning.md",
    ]),
    ("Evidence & history", "Findings, drill logs, tooling, and the early LabVIEW guides.", [
        "docs/shadow-findings.md", "docs/drill-logs/2026-07-08-b4-machine.md",
        "tools/README.md", "docs/hello-vi.md", "docs/labview-notes.md",
    ]),
]

CSS = """
:root{
  --paper:#F5F1EA; --card:#FDFBF7; --ink:#26221C; --muted:#6E6558;
  --accent:#CF551F; --signal:#1C7E8C; --good:#3C8B57; --warn:#9A6E1F; --bad:#B3382E;
  --line:#DCD4C6; --code-bg:#ECE6DA;
}
@media (prefers-color-scheme: dark){
  :root{ --paper:#201D18; --card:#2A2620; --ink:#EAE4D9; --muted:#A79B8A;
    --accent:#E8763F; --signal:#4FAEBC; --good:#6CB584; --warn:#D2A24C; --bad:#DE6D5F;
    --line:#463F35; --code-bg:#353028; }
}
*{box-sizing:border-box}
body{margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.6 "Segoe UI",system-ui,-apple-system,sans-serif;}
.bar{position:sticky; top:0; background:var(--paper); border-bottom:2px solid var(--accent);
  padding:10px 20px; display:flex; gap:14px; align-items:baseline; z-index:5;
  font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);}
.bar b{color:var(--accent)} .bar a{color:var(--muted); text-decoration:none}
.bar a:hover{color:var(--accent)}
main{max-width:900px; margin:0 auto; padding:34px 24px 70px;}
h1{font-size:30px; line-height:1.2; font-weight:650; margin:0 0 14px; text-wrap:balance;}
h2{font-size:21px; font-weight:650; margin:34px 0 10px; padding-top:10px;
  border-top:1px solid var(--line);}
h3{font-size:17px; font-weight:650; margin:24px 0 8px;}
h4{font-size:15px; font-weight:650; margin:18px 0 6px; color:var(--muted);
  letter-spacing:.06em; text-transform:uppercase;}
p{margin:0 0 12px} li{margin-bottom:4px} ul,ol{padding-left:26px; margin:0 0 12px}
a{color:var(--signal)} a:hover{color:var(--accent)}
code{font-family:Consolas,"SF Mono",Menlo,monospace; font-size:.86em;
  background:var(--code-bg); padding:.08em .35em; border-radius:3px;}
pre{background:var(--code-bg); border:1px solid var(--line); padding:12px 14px;
  overflow-x:auto; border-radius:4px; margin:0 0 14px;}
pre code{background:none; padding:0; font-size:13px; line-height:1.5;}
blockquote{border-left:4px solid var(--accent); background:var(--card);
  margin:0 0 14px; padding:10px 16px; color:var(--muted);}
blockquote p:last-child{margin-bottom:0}
.tw{overflow-x:auto; margin:0 0 14px; border:1px solid var(--line); background:var(--card);}
table{border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums;}
th,td{padding:8px 12px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line);}
thead th{font-size:11.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted);
  border-bottom:2px solid var(--line);}
tbody tr:last-child td{border-bottom:none}
hr{border:none; border-top:1px solid var(--line); margin:26px 0;}
del{color:var(--muted)}
img{max-width:100%}
details{margin:0 0 14px; border:1px solid var(--line); background:var(--card); padding:8px 14px;}
summary{cursor:pointer; font-weight:600}
.mermaid{background:var(--card); border:1px solid var(--line); padding:14px;
  margin:0 0 14px; overflow-x:auto; text-align:center;}
footer{max-width:900px; margin:0 auto; padding:0 24px 40px; color:var(--muted);
  font-size:12px; border-top:1px solid var(--line); padding-top:12px;}
/* index page */
.grp{margin-bottom:30px}
.grp > p{color:var(--muted); font-size:14px; margin-bottom:10px}
.doc{background:var(--card); border:1px solid var(--line); border-left:4px solid var(--signal);
  padding:10px 16px; margin-bottom:8px; display:block; text-decoration:none; color:var(--ink);}
.doc:hover{border-left-color:var(--accent); color:var(--ink)}
.doc b{display:block; font-size:15.5px}
.doc span{color:var(--muted); font-size:13px}
"""

MERMAID = (
    '<script type="module">'
    'try{const m=await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/'
    'mermaid.esm.min.mjs");m.default.initialize({startOnLoad:true,theme:'
    'window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"neutral"});}'
    "catch(e){/* offline: the fallback source stays visible */}"
    "</script>"
)


def page(title: str, body: str, crumb: str, src: str, depth: int) -> str:
    home = "../" * depth + "index.html"
    stamp = datetime.date.today().isoformat()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(title)} — MONARCH docs</title>
<style>{CSS}</style></head><body>
<div class="bar"><b>◆ MONARCH docs</b><a href="{home}">index</a><span>{html_mod.escape(crumb)}</span></div>
<main>{body}</main>
<footer>Generated {stamp} by tools/build_docs_html.py from <code>{html_mod.escape(src)}</code> —
the markdown is the source of truth; re-run the tool after editing it.</footer>
{MERMAID}</body></html>"""


def extract_mermaid(md_text: str) -> tuple[str, list[str]]:
    """Pull ```mermaid fences out before conversion; return placeholders."""
    blocks: list[str] = []

    def repl(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\nMERMAIDBLOCK{len(blocks) - 1}MARKER\n"

    return re.sub(r"```mermaid\n(.*?)```", repl, md_text, flags=re.S), blocks


def restore_mermaid(body: str, blocks: list[str]) -> str:
    for i, src in enumerate(blocks):
        esc = html_mod.escape(src)
        block = (f'<div class="mermaid">{esc}</div>'
                 f"<details><summary>diagram source (offline fallback)</summary>"
                 f"<pre><code>{esc}</code></pre></details>")
        body = re.sub(rf"<p>\s*MERMAIDBLOCK{i}MARKER\s*</p>|MERMAIDBLOCK{i}MARKER",
                      block, body)
    return body


def rewrite_links(body: str, src_rel: Path, targets: set[Path]) -> str:
    """Point links at sibling .md files to the generated .html pages."""

    def repl(m: re.Match) -> str:
        href = m.group(1)
        if href.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        path_part, _, frag = href.partition("#")
        if not path_part.endswith(".md"):
            return m.group(0)
        resolved = (src_rel.parent / path_part)
        try:
            resolved = Path(*[p for p in resolved.parts if p != "."])
            while ".." in resolved.parts:
                parts = list(resolved.parts)
                i = parts.index("..")
                if i == 0:
                    return m.group(0)
                del parts[i - 1:i + 1]
                resolved = Path(*parts)
        except ValueError:
            return m.group(0)
        if resolved in targets:
            new = path_part[:-3] + ".html" + (f"#{frag}" if frag else "")
            return f'href="{new}"'
        return m.group(0)

    return re.sub(r'href="([^"]+)"', repl, body)


def first_blurb(md_text: str) -> str:
    for line in md_text.splitlines():
        s = line.strip().lstrip(">*").strip()
        if s and not s.startswith(("#", "|", "```", "-", "[")):
            s = re.sub(r"[*_`]|\[([^\]]*)\]\([^)]*\)", r"\1", s)
            return (s[:150] + "…") if len(s) > 150 else s
    return ""


def build() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc"])
    targets = set(SOURCES)
    titles: dict[Path, str] = {}
    blurbs: dict[Path, str] = {}

    for rel in SOURCES:
        src = ROOT / rel
        text = src.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, flags=re.M)
        titles[rel] = re.sub(r"[*_`]", "", m.group(1)).strip() if m else rel.name
        blurbs[rel] = first_blurb(re.sub(r"^#\s+.+$", "", text, count=1, flags=re.M))

        text, mermaid_blocks = extract_mermaid(text)
        md.reset()
        body = md.convert(text)
        body = restore_mermaid(body, mermaid_blocks)
        body = body.replace("<table>", '<div class="tw"><table>').replace(
            "</table>", "</table></div>")
        body = rewrite_links(body, rel, targets)

        out = OUT / rel.with_suffix(".html")
        out.parent.mkdir(parents=True, exist_ok=True)
        depth = len(rel.parts) - 1
        out.write_text(page(titles[rel], body, str(rel), str(rel), depth),
                       encoding="utf-8")

    # index
    items = []
    listed: set[str] = set()
    for heading, blurb, paths in GROUPS:
        items.append(f'<div class="grp"><h2>{html_mod.escape(heading)}</h2>'
                     f"<p>{html_mod.escape(blurb)}</p>")
        for p in paths:
            rel = Path(p)
            listed.add(p)
            if rel not in targets:
                continue
            href = str(rel.with_suffix(".html"))
            items.append(
                f'<a class="doc" href="{href}"><b>{html_mod.escape(titles[rel])}</b>'
                f"<span>{html_mod.escape(blurbs[rel])}</span></a>")
        items.append("</div>")
    missing = [str(p) for p in SOURCES if str(p) not in listed]
    if missing:
        items.append('<div class="grp"><h2>Ungrouped</h2>')
        for p in missing:
            rel = Path(p)
            items.append(
                f'<a class="doc" href="{rel.with_suffix(".html")}">'
                f"<b>{html_mod.escape(titles[rel])}</b>"
                f"<span>{html_mod.escape(blurbs[rel])}</span></a>")
        items.append("</div>")

    body = ("<h1>MONARCH — project documentation</h1>"
            "<p>Python ⇄ LabVIEW supervisory migration for the Noble Thermodynamics "
            "Argon Power Cycle engine. These pages are generated from the repo's "
            "markdown (<code>python tools/build_docs_html.py</code>) — the markdown "
            "is the source of truth.</p>" + "".join(items))
    (OUT / "index.html").write_text(
        page("Documentation index", body, "index", "tools/build_docs_html.py", 0),
        encoding="utf-8")
    print(f"built {len(SOURCES)} pages + index → {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(build())
