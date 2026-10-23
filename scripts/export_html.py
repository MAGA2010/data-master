#!/usr/bin/env python3
"""Render the saved report.md into a self-contained, shareable HTML file.

The export is a rendering of the delivered Markdown report and nothing more.
It opens exactly two kinds of file: the report.md the run already wrote, and
the figure PNGs that report itself references. It never opens an analysis
artifact and never recomputes a number, so every value a reader sees in the
HTML is the value report.md and report.pdf carry, from the same saved
evidence.

Figures are embedded as base64 data URIs, which makes the single file
self-contained: it can be attached to an email or an issue without an asset
folder. The generator comment records the sha256 of the report.md the file
was rendered from, and `verify_artifacts.py` owns and hashes report.html as
report-stage evidence like every other deliverable -- a missing or edited
export fails verification.

Usage:
    python scripts/export_html.py --report outputs/run/report.md \
        --outdir outputs/run
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent

_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem 4rem;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.05rem; line-height: 1.65; color: #1a1a1a;
  background: #fdfdfc;
}
main { max-width: 54rem; margin: 0 auto; }
h1, h2, h3, h4, h5, h6 {
  font-family: "Helvetica Neue", Arial, sans-serif;
  line-height: 1.25; margin: 2rem 0 0.75rem; color: #111;
}
h1 { font-size: 1.7rem; border-bottom: 2px solid #333; padding-bottom: .4rem; }
h2 { font-size: 1.35rem; border-bottom: 1px solid #ccc; padding-bottom: .3rem; }
h3 { font-size: 1.12rem; }
p { margin: .7rem 0; }
table {
  border-collapse: collapse; width: 100%; margin: 1rem 0;
  font-family: "Helvetica Neue", Arial, sans-serif; font-size: .82rem;
}
th, td { border: 1px solid #bbb; padding: .35rem .5rem; text-align: left;
         vertical-align: top; }
th { background: #efefec; }
tr:nth-child(even) td { background: #f7f7f4; }
code {
  font-family: Consolas, "Courier New", monospace; font-size: .88em;
  background: #f0f0ec; padding: .08em .3em; border-radius: 3px;
}
pre { background: #f0f0ec; padding: .8rem; overflow-x: auto; }
pre code { background: none; padding: 0; }
blockquote {
  margin: 1rem 0; padding: .5rem 1rem; border-left: 4px solid #999;
  background: #f4f4f0; color: #333;
}
blockquote p { margin: .3rem 0; }
figure { margin: 1.4rem 0; text-align: center; }
figure img { max-width: 100%; height: auto; border: 1px solid #ddd; }
figcaption {
  font-family: "Helvetica Neue", Arial, sans-serif; font-size: .85rem;
  color: #444; margin-top: .5rem;
}
hr { border: 0; border-top: 1px solid #ccc; margin: 2rem 0; }
footer {
  margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ccc;
  font-family: "Helvetica Neue", Arial, sans-serif; font-size: .8rem; color: #555;
}
.html-figure-missing {
  display: block; border: 2px dashed #b33; color: #b33; padding: 1rem;
  font-family: "Helvetica Neue", Arial, sans-serif; font-size: .9rem;
}
@media print {
  body { padding: 0; background: #fff; }
  figure { page-break-inside: avoid; }
}
""".strip()


def escape(text: str) -> str:
    import html
    return html.escape(text, quote=False)


def _escape_attr(text: str) -> str:
    import html
    return html.escape(text, quote=True)


class _Renderer:
    """Markdown subset used by the reports: headings, tables, quotes, lists,
    fenced code, rules, images, links, code spans, bold and italic.

    Anything the parser does not recognise is emitted as escaped text, so an
    unknown construct degrades to readable prose instead of vanishing -- an
    export that silently dropped a sentence would misrepresent the evidence.
    """

    _IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
    _LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
    _CODE_SPAN = re.compile(r"`([^`]+)`")
    _BOLD = re.compile(r"\*\*([^*]+?)\*\*")
    _ITALAR = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
    _ITALUL = re.compile(r"(?<![\w\\])_([^_\n]+?)_(?![\w])")
    _FENCE = re.compile(r"^```")
    _HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

    def __init__(self, outdir: Path) -> None:
        self.outdir = outdir
        self.images_embedded = 0
        self.images_missing: List[str] = []

    @staticmethod
    def _safe_href(url: str) -> Optional[str]:
        """Allow only relative artifact paths, http(s) and mailto.

        The export renders markdown the reports generated, but it also renders
        whatever a modified report.md holds, and a shareable HTML file travels
        further than the run directory. A javascript:/data: URL becomes a
        script the moment someone opens the export, so an unrecognised scheme
        is emitted as plain text instead of a link.
        """
        colon = url.find(":")
        if colon == -1:
            return url                       # relative path, no scheme
        scheme = url[:colon].strip().lower()
        return url if scheme in ("http", "https", "mailto") else None

    # ---------------- inline ----------------
    def _inline(self, text: str) -> str:
        out: List[str] = []
        pos = 0
        pattern = re.compile(
            r"`([^`]+)`"                      # code span first: its content
            r"|!\[[^\]]*\]\([^)]+\)"          # then images
            r"|\[[^\]]+\]\([^)]+\)"           # then links
        )
        for match in pattern.finditer(text):
            out.append(self._emphasis(escape(text[pos:match.start()])))
            token = match.group(0)
            if token.startswith("`"):
                out.append("<code>%s</code>" % escape(match.group(1)))
            elif token.startswith("!"):
                out.append(self._image(token))
            else:
                link = self._LINK.match(token)
                if link:
                    href = self._safe_href(link.group(2))
                    label = self._emphasis(escape(link.group(1)))
                    if href is not None:
                        out.append('<a href="%s">%s</a>'
                                   % (_escape_attr(href), label))
                    else:  # hostile scheme: keep the label, drop the href
                        out.append("%s (%s)" % (label, escape(link.group(2))))
                else:  # unreachable; keep the raw text rather than drop it
                    out.append(escape(token))
            pos = match.end()
        out.append(self._emphasis(escape(text[pos:])))
        return "".join(out)

    def _emphasis(self, escaped: str) -> str:
        escaped = self._BOLD.sub(r"<strong>\1</strong>", escaped)
        escaped = self._ITALAR.sub(r"<em>\1</em>", escaped)
        escaped = self._ITALUL.sub(r"<em>\1</em>", escaped)
        return escaped

    def _image(self, token: str) -> str:
        match = self._IMAGE.match(token)
        alt, src = match.group(1), match.group(2)
        path = Path(src)
        if not path.is_absolute():
            path = self.outdir / path
        mime = _IMAGE_TYPES.get(path.suffix.lower())
        if path.is_file() and mime:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            self.images_embedded += 1
            return ('<img src="data:%s;base64,%s" alt="%s">'
                    % (mime, data, _escape_attr(alt)))
        # A dropped figure is an evidence gap, so the export says so on the
        # page instead of quietly rendering a shorter report.
        self.images_missing.append(src)
        return ('<span class="html-figure-missing">Figure file not found next to '
                'report.md: %s</span>' % escape(src))

    # ---------------- blocks ----------------
    def _table_rows(self, lines: List[str]) -> List[List[str]]:
        rows = []
        for line in lines:
            cells = line.strip().strip("|").split("|")
            rows.append([c.strip() for c in cells])
        return rows

    def render(self, md_text: str) -> str:
        lines = md_text.splitlines()
        parts: List[str] = []
        i = 0
        in_list: Optional[str] = None  # "ul" | "ol" while a list is open

        def close_list() -> None:
            nonlocal in_list
            if in_list:
                parts.append("</%s>" % in_list)
                in_list = None

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                close_list()
                i += 1
                continue

            if self._FENCE.match(line):
                close_list()
                body: List[str] = []
                i += 1
                while i < len(lines) and not self._FENCE.match(lines[i]):
                    body.append(lines[i])
                    i += 1
                i += 1  # closing fence (or end of file)
                parts.append("<pre><code>%s</code></pre>"
                             % escape("\n".join(body)))
                continue

            if stripped.startswith("|") and i + 1 < len(lines) \
                    and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) \
                    and "-" in lines[i + 1]:
                close_list()
                block: List[str] = [line]
                i += 1
                while i < len(lines) and lines[i].strip().startswith("|"):
                    block.append(lines[i])
                    i += 1
                rows = self._table_rows(block)
                header, data = rows[0], rows[2:]
                parts.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
                    "".join("<th>%s</th>" % self._inline(c) for c in header),
                    "".join("<tr>%s</tr>" % "".join(
                        "<td>%s</td>" % self._inline(c) for c in row)
                        for row in data if row)))
                continue

            heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if heading:
                close_list()
                level = len(heading.group(1))
                parts.append("<h%d>%s</h%d>"
                             % (level, self._inline(heading.group(2)), level))
                i += 1
                continue

            if self._HR.match(stripped):
                close_list()
                parts.append("<hr>")
                i += 1
                continue

            if stripped.startswith(">"):
                close_list()
                quote: List[str] = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                # a quote can hold figures; fold the nested counts into ours
                nested = _Renderer(self.outdir)
                inner = nested.render("\n".join(quote))
                self.images_embedded += nested.images_embedded
                self.images_missing.extend(nested.images_missing)
                parts.append("<blockquote>%s</blockquote>" % inner)
                continue

            bullet = re.match(r"^[-*]\s+(.*)$", stripped)
            ordered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
            if bullet or ordered:
                want = "ul" if bullet else "ol"
                if in_list != want:
                    close_list()
                    parts.append("<%s>" % want)
                    in_list = want
                parts.append("<li>%s</li>"
                             % self._inline((bullet or ordered).group(1)))
                i += 1
                continue

            # paragraph: one blank-line-delimited run of lines
            close_list()
            para: List[str] = [stripped]
            i += 1
            while i < len(lines) and lines[i].strip() \
                    and not lines[i].strip().startswith(("|", ">", "#", "```")) \
                    and not self._HR.match(lines[i].strip()) \
                    and not re.match(r"^[-*]\s+", lines[i].strip()) \
                    and not re.match(r"^\d+[.)]\s+", lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            parts.append("<p>%s</p>" % self._inline(" ".join(para)))

        close_list()
        return "\n".join(parts)


def render_report_html(md_path: Path, outdir: Optional[Path] = None,
                       title: Optional[str] = None) -> Dict[str, Any]:
    """Write report.html next to report.md and describe what was rendered.

    The output is deterministic for a given report.md and figure set: no
    timestamp of its own is inserted, so an unchanged report re-exports to
    identical bytes.
    """
    md_path = Path(md_path)
    outdir = Path(outdir) if outdir else md_path.parent
    md_text = md_path.read_text(encoding="utf-8")
    sha = hashlib.sha256(md_text.encode("utf-8")).hexdigest()
    if not title:
        first = next((l[2:].strip() for l in md_text.splitlines()
                      if l.startswith("# ")), "data-master report")
        title = first

    renderer = _Renderer(outdir)
    body = renderer.render(md_text)
    note = ("generated from report.md (sha256 %s) by scripts/export_html.py; "
            "every number is that of the saved report, nothing was recalculated"
            % sha)
    page = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n<main>\n"
        "<!-- data-master HTML export: %s -->\n%s\n</main>\n"
        "<footer>This file is an export of <code>report.md</code> from a "
        "data-master run. The Markdown, the PDF and the machine-readable "
        "evidence in the run directory remain the records of account.</footer>\n"
        "</body>\n</html>\n"
        % (_escape_attr(title), _STYLE, note, body))
    out_path = outdir / "report.html"
    out_path.write_text(page, encoding="utf-8", newline="\n")
    return {
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
        "source_md": str(md_path),
        "source_md_sha256": sha,
        "images_embedded": renderer.images_embedded,
        "images_missing": renderer.images_missing,
        "self_contained": not renderer.images_missing,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a saved report.md as self-contained HTML. "
                    "No artifact is opened and no number is recalculated.")
    parser.add_argument("--report", required=True, help="path to report.md")
    parser.add_argument("--outdir", help="run directory (default: report's parent)")
    parser.add_argument("--title", help="page title (default: report's H1)")
    args = parser.parse_args(argv)
    md_path = Path(args.report)
    if not md_path.is_file():
        print("report not found: %s" % md_path, file=sys.stderr)
        return 2
    info = render_report_html(md_path, outdir=Path(args.outdir) if args.outdir
                              else None, title=args.title)
    print("[html] report.html %s (%d bytes, %d figure(s) embedded)"
          % (info["path"], info["bytes"], info["images_embedded"]))
    if info["images_missing"]:
        for src in info["images_missing"]:
            print("[html] WARNING: figure not found: %s" % src, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
