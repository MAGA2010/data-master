#!/usr/bin/env python3
"""Markdown -> HTML -> PDF through a headless browser. Third-tier backend.

Used when neither reportlab nor fpdf2 is importable.  It exists because the
most likely cause of "no PDF backend" is a machine without the optional
packages, and a machine with a browser almost certainly still deserves a PDF
rather than only a markdown file.

Images are inlined as data URIs: a file:// page loading relative assets works
in most builds but fails under some headless sandbox combinations, and a report
whose figures silently vanish is the failure mode this file exists to avoid.

Limitations, recorded in the provenance so a reader is not misled:
page numbers are not available, because Chrome's print path has no page-number
template; the TOC is rendered as a plain list without page numbers.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
]

CSS = """
@page { size: A4 portrait; margin: 17mm 15mm 16mm 15mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "Segoe UI", -apple-system, "Helvetica Neue", Arial,
               "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB",
               "Noto Sans CJK SC", sans-serif;
  font-size: 9.6pt; line-height: 1.48; color: #1a1a1a; margin: 0;
}
h1 { font-size: 19pt; color: #1f4e79; margin: 0 0 4pt 0; line-height: 1.2; }
h1 + p { color: #5a5a5a; font-size: 9pt; margin-top: 0; }
h2 {
  font-size: 14pt; color: #1f4e79; margin: 16pt 0 6pt 0;
  border-bottom: 0.6pt solid #c9c9c9; padding-bottom: 2pt;
  page-break-after: avoid;
}
h3 { font-size: 11.6pt; margin: 11pt 0 4pt 0; page-break-after: avoid; }
h4 { font-size: 10.2pt; font-style: italic; color: #5a5a5a; margin: 8pt 0 3pt 0;
     page-break-after: avoid; }
p { margin: 0 0 6pt 0; text-align: justify; orphans: 3; widows: 3; }
blockquote {
  margin: 6pt 0; padding: 5pt 8pt; background: #f4f6f8;
  border-left: 2.5pt solid #c9c9c9; color: #4a4a4a; font-size: 9pt;
}
ul, ol { margin: 0 0 6pt 0; padding-left: 16pt; }
li { margin-bottom: 2pt; }
code {
  font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
  font-size: 8.6pt; background: #f0f0f0; padding: 0 2pt; border-radius: 2pt;
}
pre {
  background: #f6f7f9; border: 0.5pt solid #dcdfe3; padding: 6pt 8pt;
  font-size: 8.4pt; line-height: 1.38; overflow: hidden;
  white-space: pre-wrap; word-wrap: break-word;
  page-break-inside: avoid;
}
pre code { background: none; padding: 0; }
table {
  border-collapse: collapse; width: 100%; margin: 5pt 0 9pt 0;
  font-size: 8.2pt; page-break-inside: avoid;
}
th {
  background: #1f4e79; color: #fff; text-align: left; font-weight: 600;
  padding: 3.5pt 4pt; border: 0.4pt solid #98a8b8;
}
td { padding: 3.5pt 4pt; border: 0.4pt solid #c9c9c9; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f4f6f8; }
hr { border: none; border-top: 0.6pt solid #c9c9c9; margin: 9pt 0; }
figure { margin: 8pt 0 12pt 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: 8.4pt; color: #5a5a5a; text-align: left; margin-top: 3pt; }
.toc { font-size: 9pt; }
.toc a { color: #1a1a1a; text-decoration: none; }
.pagebreak { page-break-before: always; }
img.missing { color: #a00; font-size: 8pt; font-style: italic; }
"""

INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<img>!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<link>\[(?P<ltext>[^\]]+)\]\((?P<href>[^)\s]+)\))"
    r"|(?P<strong>\*\*(?P<stext>[^*]+)\*\*)"
    r"|(?P<em>(?<![*\w])\*(?P<etext>[^*\n]+)\*(?![*\w]))"
)


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def data_uri(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "image/png")
    return "data:%s;base64,%s" % (mime,
                                   base64.b64encode(path.read_bytes()).decode("ascii"))


def inline_html(text: str, base_dir: Path) -> str:
    out, pos = [], 0
    for m in INLINE_RE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        g = m.groupdict()
        if g["code"]:
            out.append("<code>%s</code>" % esc(g["code"][1:-1]))
        elif g["img"]:
            p = (base_dir / g["src"])
            if p.exists():
                out.append('<img src="%s" alt="%s" />' % (data_uri(p), esc(g["alt"])))
            else:
                out.append('<span class="missing">[figure missing: %s]</span>'
                           % esc(g["src"]))
        elif g["link"]:
            href = g["href"]
            if not re.match(r"^[a-z]+://", href):
                href = "https://" + href
            out.append('<a href="%s">%s</a>' % (esc(href), esc(g["ltext"])))
        elif g["strong"]:
            out.append("<strong>%s</strong>" % esc(g["stext"]))
        elif g["em"]:
            out.append("<em>%s</em>" % esc(g["etext"]))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def split_row(line: str):
    line = line.strip().strip("|")
    return [c.strip() for c in line.split("|")]


def is_sep(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and \
        bool(re.fullmatch(r"\|[\s:\-|]+\|", s)) and "-" in s


def build_toc(lines):
    entries = []
    for ln in lines:
        m = re.match(r"^(#{2,3})\s+(.*)$", ln.strip())
        if not m:
            continue
        level = len(m.group(1)) - 1
        text = re.sub(r"[*`\[\]]", "", m.group(2)).strip()
        if level > 2:
            continue
        entries.append('<div style="padding-left:%dpt">%s</div>'
                       % ((level - 1) * 14, esc(text)))
    return '<div class="toc">%s</div>' % "".join(entries) if entries else ""


def markdown_to_html(md_text: str, base_dir: Path, with_toc=True) -> str:
    lines = md_text.splitlines()
    body, i, n = [], 0, len(lines)
    first_h1_done = False
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            lang, i = s[3:].strip(), i + 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code = esc("\n".join(buf))
            body.append("<pre><code>%s</code></pre>" % (code or "&nbsp;"))
            continue
        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", s):
            body.append("<hr />")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if level == 1 and not first_h1_done:
                first_h1_done = True
                body.append("<h1>%s</h1>" % inline_html(text, base_dir))
            elif level == 1:
                body.append('<div class="pagebreak"></div><h1>%s</h1>'
                            % inline_html(text, base_dir))
            else:
                tag = "h%d" % min(level, 4)
                body.append("<%s>%s</%s>" % (tag, inline_html(text, base_dir), tag))
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and is_sep(lines[i + 1]):
            head = split_row(lines[i])
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            out = ["<table><thead><tr>"]
            out += ["<th>%s</th>" % inline_html(c, base_dir) for c in head]
            out.append("</tr></thead><tbody>")
            for r in rows:
                out.append("<tr>" + "".join("<td>%s</td>" % inline_html(c, base_dir)
                                            for c in r) + "</tr>")
            out.append("</tbody></table>")
            body.append("".join(out))
            continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            body.append("<blockquote>%s</blockquote>"
                        % inline_html(" ".join(x.strip() for x in buf if x.strip()),
                                      base_dir))
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            tag = "ol" if s[0].isdigit() else "ul"
            body.append("<%s>" % tag)
            counters = 0
            while i < n:
                cur = lines[i]
                cs = cur.strip()
                mm2 = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", cs)
                if not mm2:
                    if cs == "" and i + 1 < n and re.match(
                            r"^([-*+]|\d+[.)])\s+", lines[i + 1].strip()):
                        i += 1
                        continue
                    break
                indent = len(cur) - len(cur.lstrip())
                pad = 14 if indent >= 2 else 0
                counters += 1
                if tag == "ol":
                    lab = "%d." % counters
                else:
                    lab = "•" if pad == 0 else "–"
                body.append('<li style="padding-left:%dpt">%s</li>'
                            % (pad, inline_html(mm2.group(2), base_dir)))
                i += 1
            body.append("</%s>" % tag)
            continue
        solo = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", s)
        if solo:
            p = base_dir / solo.group(2)
            if p.exists():
                # alt is kept for accessibility; no visible figcaption -- the
                # report writer already prints the caption above the image.
                body.append('<figure><img src="%s" alt="%s" /></figure>'
                            % (data_uri(p), esc(solo.group(1))))
            else:
                body.append('<p class="missing">[figure missing: %s]</p>'
                            % esc(solo.group(2)))
            i += 1
            continue
        buf = [s]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if not nxt:
                break
            if (re.match(r"^#{1,6}\s", nxt) or nxt.startswith(("|", ">", "```"))
                    or re.match(r"^([-*+]|\d+[.)])\s+", nxt)
                    or re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}", nxt)):
                break
            buf.append(nxt)
            i += 1
        body.append("<p>%s</p>" % inline_html(" ".join(buf), base_dir))
    toc = "<h2>Contents</h2>" + build_toc(lines) if with_toc else ""
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<title>data-master report</title><style>%s</style></head><body>%s%s</body></html>"
            % (CSS, toc, "".join(body)))


def find_browser(explicit=None):
    if explicit and Path(explicit).exists():
        return Path(explicit)
    for cand in BROWSER_CANDIDATES:
        if Path(cand).exists():
            return Path(cand)
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser",
                 "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return Path(found)
    env = os.environ.get("BROWSER")
    if env and Path(env).exists():
        return Path(env)
    return None


def render(md_path: Path, pdf_path: Path, browser=None, timeout=90) -> dict:
    html = markdown_to_html(md_path.read_text(encoding="utf-8"), md_path.parent)
    exe = find_browser(browser)
    if exe is None:
        raise RuntimeError("no Chromium-family browser found")
    with tempfile.TemporaryDirectory(prefix="dm_pdf_") as tmp:
        tmpdir = Path(tmp)
        page = tmpdir / "report.html"
        page.write_text(html, encoding="utf-8")
        out = tmpdir / "out.pdf"
        cmd = [
            str(exe),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-extensions",
            "--no-first-run",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=10000",
            "--user-data-dir=%s" % (tmpdir / "profile"),
            "--print-to-pdf=%s" % out,
            page.resolve().as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not out.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
            raise RuntimeError("browser produced no PDF: %s" % (" | ".join(tail) or "no output"))
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, pdf_path)
    data = pdf_path.read_bytes()
    return {
        "backend": "headless-browser",
        "browser": str(exe),
        "bytes": len(data),
        "pages": len(re.findall(rb"/Type\s*/Page[^s]", data)) or -1,
        "limitations": ["no page numbers (Chrome print path has no page-number template)",
                        "table of contents has no page numbers"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown -> PDF via headless browser")
    ap.add_argument("--md", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--browser", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    info = render(Path(a.md), Path(a.pdf), a.browser)
    if a.json:
        print(json.dumps(info, indent=2))
    else:
        print("headless-browser: %s -> %s (%d bytes)" % (a.md, a.pdf, info["bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
