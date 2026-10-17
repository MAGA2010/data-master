#!/usr/bin/env python3
"""Markdown -> PDF with fpdf2.  Tier 3 of the cascade: last resort, not first choice.

This file used to import `fpdf.md.Markdown`.  That module does not exist in
fpdf2 2.8.x, so the tier failed on every machine that installed the package it
claims to need.  The real fpdf2 API is `multi_cell` / `image`, and this renderer
uses exactly those.

It is deliberately the last tier.  Headless Chrome prints the report's own HTML,
so figures, tables and CSS survive intact; fpdf2 lays the document out itself and
gets a faithful-but-plainer result.  The cascade therefore runs
reportlab -> headless-browser -> fpdf2.

CJK needs a real TrueType font, because the built-in PDF fonts have no Chinese
glyphs.  When the text contains CJK and no system font can be found, this tier
fails loudly instead of emitting black boxes.

Usage
    python scripts/_md2pdf_fpdf.py --md report.md --pdf report.pdf [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
CODE_RE = re.compile(r"`([^`]+)`")
ITAL_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def needs_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text or ""))


def find_font(needed: bool) -> Optional[Path]:
    if not needed:
        return None
    for candidate in FONT_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return p
    return None


def plain(text: str) -> str:
    """Strip the inline markdown that a PDF body font cannot express."""
    text = LINK_RE.sub(r"\1", text)
    text = BOLD_RE.sub(r"\1", text)
    text = CODE_RE.sub(r"\1", text)
    text = ITAL_RE.sub(r"\1", text)
    return text.replace("**", "").replace("`", "")


def split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def is_sep(line: str) -> bool:
    s = line.strip()
    return bool(re.fullmatch(r"\|?[\s:\-|]+\|?", s)) and "-" in s


def render(md_path: Path, pdf_path: Path) -> Dict[str, Any]:
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError(
            "fpdf2 is not installed: pip install fpdf2. This tier is optional; the "
            "report cascade falls through to the browser backend without it."
        ) from exc

    text = md_path.read_text(encoding="utf-8")
    want_cjk = needs_cjk(text)
    font_path = find_font(want_cjk)
    if want_cjk and font_path is None:
        raise RuntimeError(
            "the report contains CJK characters and no CJK-capable system font was "
            "found. This tier cannot render them without black boxes; install "
            "reportlab (pip install reportlab) or use the browser tier."
        )

    class Doc(FPDF):
        def header(self) -> None:                      # no running header
            pass

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font(family, "", 7.5)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, "data-master report  |  page %d" % self.page_no(),
                      align="R")

    pdf = Doc(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.set_title(md_path.stem)
    pdf.set_author("data-master")
    pdf.set_creator("data-master fpdf2 backend")
    pdf.add_page()

    family = "helvetica"
    if font_path is not None:
        try:
            pdf.add_font("dmcjk", "", str(font_path))
            pdf.add_font("dmcjk", "B", str(font_path))
            family = "dmcjk"
        except Exception as exc:
            raise RuntimeError("could not register the CJK font %s: %s"
                               % (font_path, exc))

    def set_font(size: float, bold: bool = False, grey: bool = False) -> None:
        pdf.set_font(family, "B" if bold else "", size)
        pdf.set_text_color(90, 90, 90) if grey else pdf.set_text_color(26, 26, 26)

    def para(body: str, size: float = 9.6, bold: bool = False, grey: bool = False,
             indent: float = 0.0, before: float = 1.0, after: float = 2.0) -> None:
        set_font(size, bold, grey)
        if before:
            pdf.ln(before)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, size * 0.48, body, align="L")
        if after:
            pdf.ln(after)

    def table(rows: List[List[str]], avail: float) -> None:
        """Draw a table whose borders and wrapped text agree with each other.

        Two bugs lived here.  multi_cell was given the whole row height as its
        *line* height, so the text sat at the bottom of an oversized cell; and it
        was left with the default WORD wrap, so `sepal_width_cm` overflowed a
        narrow column instead of breaking.  The row is now drawn as one filled
        rectangle with per-column rules, and each cell text is laid out inside it
        with CHAR wrapping.
        """
        if not rows:
            return
        cols = max(len(r) for r in rows)
        rows = [r + [""] * (cols - len(r)) for r in rows]
        # Width by the longest unbreakable token plus half of the longest cell:
        # a column holding "= 9.2e-24" needs room for that token, while a column
        # holding a long sentence should be allowed to wrap.
        lengths = []
        for i in range(cols):
            cells = [plain(r[i]) for r in rows]
            token = max((len(t) for c in cells for t in c.split()), default=4)
            whole = max((len(c) for c in cells), default=4)
            lengths.append(max(6.0, token + 1.0, min(28.0, whole * 0.55)))
        total = float(sum(lengths)) or 1.0
        widths = [avail * v / total for v in lengths]
        line_h = 3.9
        size = 7.7
        pad = 1.1

        def n_lines(txt_: str, w: float) -> int:
            pdf.set_font(family, "", size)
            try:
                return max(1, len(pdf.multi_cell(w - 2 * pad, line_h, plain(txt_),
                                                 dry_run=True, output="LINES",
                                                 wrapmode="CHAR")))
            except Exception:
                return max(1, int(len(plain(txt_)) / max(w / 1.9, 4)) + 1)

        def draw_row(cells: List[str], header: bool) -> None:
            heights = [n_lines(c, widths[i]) * line_h + 2 * pad
                       for i, c in enumerate(cells)]
            h = max(heights) if heights else line_h + 2 * pad
            x0, y0 = pdf.l_margin, pdf.get_y()
            if header:
                pdf.set_fill_color(31, 78, 121)
                pdf.set_draw_color(31, 78, 121)
            else:
                pdf.set_fill_color(244, 246, 248)
                pdf.set_draw_color(205, 205, 205)
            pdf.rect(x0, y0, sum(widths), h, style="DF")

            for i, c in enumerate(cells):
                pdf.set_xy(x0 + sum(widths[:i]) + pad, y0 + pad)
                pdf.set_font(family, "B" if header else "", size)
                pdf.set_text_color(255, 255, 255) if header else pdf.set_text_color(26, 26, 26)
                pdf.multi_cell(widths[i] - 2 * pad, line_h, plain(c), border=0,
                               align="L", wrapmode="CHAR", new_x="RIGHT",
                               new_y="TOP")
            pdf.set_draw_color(205, 205, 205)
            x = x0
            for w in widths:
                pdf.line(x, y0, x, y0 + h)
                x += w
            pdf.line(x, y0, x, y0 + h)
            pdf.line(x0, y0 + h, x, y0 + h)
            pdf.set_xy(x0, y0 + h)

        draw_row(rows[0], True)
        for row in rows[1:]:
            if pdf.get_y() > pdf.h - 28:
                pdf.add_page()
                draw_row(rows[0], True)
            draw_row(row, False)
        pdf.ln(4)

    lines = text.splitlines()
    avail = pdf.w - pdf.l_margin - pdf.r_margin
    i, n = 0, len(lines)
    figure_count = 0
    while i < n:
        raw = lines[i]
        s = raw.strip()

        if not s:
            i += 1
            continue

        if s.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            set_font(7.6, grey=True)
            pdf.set_fill_color(244, 246, 248)
            pdf.multi_cell(0, 3.6, "\n".join(buf) or " ", border=0, fill=True)
            pdf.ln(2)
            continue

        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", s):
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin,
                     pdf.get_y() + 2)
            pdf.ln(4)
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            body = plain(m.group(2))
            if level == 1:
                if pdf.get_y() > 22:
                    pdf.add_page()
                pdf.set_text_color(31, 78, 121)
                pdf.set_font(family, "B", 19)
                pdf.multi_cell(0, 9, body)
                pdf.set_draw_color(31, 78, 121)
                pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin,
                         pdf.get_y() + 1)
                pdf.ln(4)
            elif level == 2:
                pdf.ln(3)
                pdf.set_text_color(31, 78, 121)
                pdf.set_font(family, "B", 13.5)
                pdf.multi_cell(0, 6.6, body)
                pdf.ln(2)
            else:
                pdf.ln(2)
                pdf.set_text_color(40, 40, 40)
                pdf.set_font(family, "B", 10.8 if level == 3 else 9.8)
                pdf.multi_cell(0, 5.2, body)
                pdf.ln(1)
            i += 1
            continue

        if s.startswith("|") and i + 1 < n and is_sep(lines[i + 1]):
            rows = [split_row(s)]
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            table(rows, avail)
            continue

        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(plain(lines[i].strip()[1:].strip()))
                i += 1
            set_font(8.6, grey=True)
            pdf.set_fill_color(247, 247, 247)
            pdf.multi_cell(0, 4.4, "\n".join(buf), border=1, fill=True)
            pdf.ln(2)
            continue

        img = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", s)
        if img:
            src = md_path.parent / img.group(2)
            if src.exists():
                try:
                    w = avail * 0.98
                    pdf.image(str(src), x=pdf.l_margin, w=w)
                    figure_count += 1
                    pdf.ln(2)
                except Exception:
                    para("[figure could not be embedded: %s]" % img.group(2),
                         grey=True)
            else:
                para("[figure missing: %s]" % img.group(2), grey=True)
            i += 1
            continue

        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            while i < n:
                cur = lines[i].strip()
                mm = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", cur)
                if not mm:
                    break
                indent = len(lines[i]) - len(lines[i].lstrip())
                marker = "•" if mm.group(1) in "-*+" else mm.group(1)
                set_font(9.4)
                pdf.set_x(pdf.l_margin + 2 + (1 if indent >= 2 else 0) * 5)
                pdf.multi_cell(0, 4.6, "%s %s" % (marker, plain(mm.group(2))),
                               align="L")
                pdf.ln(0.6)
                i += 1
            pdf.ln(1)
            continue

        buf = [plain(s)]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or re.match(r"^(#{1,6})\s", nxt) or nxt.startswith("|")
                    or nxt.startswith(">") or nxt.startswith("```")
                    or re.match(r"^([-*+]|\d+[.)])\s+", nxt)
                    or re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", nxt)):
                break
            buf.append(plain(nxt))
            i += 1
        para(" ".join(buf))

    pdf.output(str(pdf_path))
    return {
        "backend": "fpdf2",
        "fpdf2_version": getattr(__import__("fpdf"), "__version__", "unknown"),
        "cjk_font_embedded": bool(font_path),
        "cjk_font_path": str(font_path) if font_path else None,
        "cjk_text_present": want_cjk,
        "n_figures": figure_count,
        "bytes": pdf_path.stat().st_size,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown -> PDF via fpdf2")
    ap.add_argument("--md", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        info = render(Path(a.md), Path(a.pdf))
    except Exception as exc:
        print("fpdf2 backend unavailable: %s" % exc, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(info, indent=2))
    else:
        print("fpdf2: %s -> %s (%d bytes)" % (a.md, a.pdf, info["bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
