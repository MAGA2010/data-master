#!/usr/bin/env python3
"""Markdown -> PDF with ReportLab, standard library only besides reportlab.

This file is deliberately standalone.  It is invoked by assemble_report.py
through whichever interpreter happens to have reportlab installed, so it must
not import pandas, numpy or anything from the data-master package: the
interpreter that can render a PDF is rarely the one that holds the data.

Supported markdown subset, which is the subset the report writer emits:
  ATX headings, paragraphs, blockquotes, horizontal rules, fenced code,
  pipe tables, bullet and ordered lists (two levels), images, and the inline
  forms **bold**, *italic*, `code`, [link](url).

Two details that are easy to get wrong and expensive to discover late:

  * CJK text.  A dataset can perfectly well have Chinese column names, and
    Helvetica has no glyphs for them -- they render as black boxes, or vanish.
    Runs containing CJK are therefore wrapped in a CID font automatically.
  * Table widths.  Long cells in a report table must not push the table off
    the page, so columns are sized from the content and wrapped.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

CJK_FONT_NAME = "STSong-Light"  # a CID font registered by register_fonts()
CJK_PATTERN = re.compile(
    "([\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\uff00-\uffef\uac00-\ud7af]+)"
)

BASE_FONT = "Helvetica"
BASE_FONT_BOLD = "Helvetica-Bold"
BASE_FONT_ITALIC = "Helvetica-Oblique"
MONO_FONT = "Courier"

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5a5a5a")
RULE = colors.HexColor("#c9c9c9")
ACCENT = colors.HexColor("#1f4e79")
PANEL_BG = colors.HexColor("#f4f6f8")


def register_fonts() -> bool:
    """Register the CJK fallback font. Returns True when available."""
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
        return True
    except Exception:
        return False


def needs_cjk(text: str) -> bool:
    return bool(CJK_PATTERN.search(text or ""))


def wrap_cjk(escaped: str, cjk_ok: bool) -> str:
    """Wrap CJK runs so they use a font that actually has the glyphs."""
    if not cjk_ok:
        return escaped
    return CJK_PATTERN.sub(r'<font face="%s">\1</font>' % CJK_FONT_NAME, escaped)


def esc(text: str) -> str:
    return _html.escape(text or "", quote=False)


# ------------------------------------------------------------------ inline

TOKEN_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<img>!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<link>\[(?P<ltext>[^\]]+)\]\((?P<href>[^)\s]+)\))"
    r"|(?P<strong>\*\*(?P<stext>[^*]+)\*\*)"
    r"|(?P<em>(?<![*\w])\*(?P<etext>[^*\n]+)\*(?![*\w]))"
)


def inline(text: str, cjk_ok: bool = True) -> str:
    """Convert inline markdown to ReportLab paragraph markup.

    Tokenising rather than escaping-then-substituting matters: escaping the
    whole line first would turn the markup we are about to insert into literal
    angle brackets.
    """
    out = []
    pos = 0
    for m in TOKEN_RE.finditer(text):
        out.append(wrap_cjk(esc(text[pos:m.start()]), cjk_ok))
        g = m.groupdict()
        if g["code"]:
            out.append('<font face="%s" size="8.2" backColor="#f0f0f0">%s</font>'
                       % (MONO_FONT, wrap_cjk(esc(g["code"][1:-1]), cjk_ok)))
        elif g["img"]:
            out.append(esc(g["alt"]))
        elif g["link"]:
            out.append('<link href="%s" color="%s">%s</link>'
                       % (esc(g["href"]), ACCENT.hexval()[2:], wrap_cjk(esc(g["ltext"]), cjk_ok)))
        elif g["strong"]:
            out.append("<b>%s</b>" % wrap_cjk(esc(g["stext"]), cjk_ok))
        elif g["em"]:
            out.append("<i>%s</i>" % wrap_cjk(esc(g["etext"]), cjk_ok))
        pos = m.end()
    out.append(wrap_cjk(esc(text[pos:]), cjk_ok))
    return "".join(out)


# ------------------------------------------------------------------- block

def split_row(line: str) -> list:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def is_table_sep(line: str) -> bool:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    return bool(re.fullmatch(r"\|[\s:\-|]+\|", s)) and "-" in s


def column_widths(rows, ncols, avail, font_size: float = 8.0):
    """Size columns from measured text, not from a character-count guess.

    The old heuristic capped every column at 46 "weight" units, so
    `fig01_distribution_panel` was given a column about a third of the width it
    needed and broke mid-word in the figure-spec table.  Here each column asks
    for the width of its longest unbreakable token, and the leftover is shared
    out; nothing is capped by an invented maximum.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    pad = 11.0                      # cell padding + grid line
    needs = []
    for i in range(ncols):
        cells = [str(rows[r][i]) for r in range(len(rows)) if i < len(rows[r])]
        tokens = [w for c in cells for w in re.sub(r"[*`\[\]]", "", c).split()]
        longest_token = max((stringWidth(w, BASE_FONT, font_size) for w in tokens),
                            default=0.0)
        # A short cell should not wrap at all; a long one is allowed to.
        whole = max((stringWidth(c, BASE_FONT, font_size) for c in cells), default=0.0)
        wants = max(longest_token + pad, min(whole + pad, avail * 0.32))
        needs.append(max(46.0, wants))

    total = sum(needs)
    if total <= 0:
        return [avail / max(ncols, 1)] * ncols
    if total < avail:
        # Hand the spare width to the columns proportionally, so a table with
        # room to breathe does not sit cramped in the left half of the page.
        return [w + (avail - total) * (w / total) for w in needs]
    return [avail * w / total for w in needs]


def make_table(rows, styles, avail, cjk_ok, font_size=8.0):
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    cell = ParagraphStyle("cell", fontName=BASE_FONT, fontSize=font_size,
                          leading=font_size + 2.6, textColor=INK, spaceAfter=0)
    head = ParagraphStyle("thead", parent=cell, fontName=BASE_FONT_BOLD,
                          textColor=colors.white)
    data = []
    for i, r in enumerate(rows):
        st = head if i == 0 else cell
        data.append([Paragraph(inline(c, cjk_ok), st) for c in r])
    t = Table(data, colWidths=column_widths(rows, ncols, avail, font_size), repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL_BG]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def place_image(src: Path, alt: str, avail_w: float, avail_h: float, dpi_hint=200.0):
    from reportlab.lib.utils import ImageReader
    reader = ImageReader(str(src))
    iw, ih = reader.getSize()
    if iw <= 0 or ih <= 0:
        return None
    # ImageReader reports pixels for bitmaps; convert to points via dpi.
    if iw > 2000 or ih > 2000:
        w = iw / dpi_hint * 72.0
        h = ih / dpi_hint * 72.0
    else:
        w, h = float(iw), float(ih)
    scale = min(1.0, avail_w / w, avail_h / h)
    return Image(str(src), width=w * scale, height=h * scale)


# ------------------------------------------------------------------ styles

def build_styles():
    ss = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("dm_title", parent=ss["Title"], fontName=BASE_FONT_BOLD,
                                fontSize=19, leading=23, textColor=ACCENT,
                                alignment=TA_LEFT, spaceAfter=4)
    s["subtitle"] = ParagraphStyle("dm_subtitle", parent=ss["Normal"], fontName=BASE_FONT,
                                   fontSize=9.5, leading=13, textColor=MUTED, spaceAfter=10)
    s["h1"] = ParagraphStyle("dm_h1", parent=ss["Heading1"], fontName=BASE_FONT_BOLD,
                             fontSize=14.5, leading=18, textColor=ACCENT,
                             spaceBefore=6, spaceAfter=8)
    s["h2"] = ParagraphStyle("dm_h2", parent=ss["Heading2"], fontName=BASE_FONT_BOLD,
                             fontSize=11.8, leading=15, textColor=INK,
                             spaceBefore=10, spaceAfter=5)
    s["h3"] = ParagraphStyle("dm_h3", parent=ss["Heading3"], fontName=BASE_FONT_BOLD,
                             fontSize=10.4, leading=13.5, textColor=colors.HexColor("#333333"),
                             spaceBefore=8, spaceAfter=4)
    s["h4"] = ParagraphStyle("dm_h4", parent=ss["Heading4"], fontName=BASE_FONT_ITALIC,
                             fontSize=9.8, leading=13, textColor=MUTED,
                             spaceBefore=6, spaceAfter=3)
    s["body"] = ParagraphStyle("dm_body", parent=ss["BodyText"], fontName=BASE_FONT,
                               fontSize=9.4, leading=13.6, textColor=INK,
                               alignment=TA_JUSTIFY, spaceAfter=6)
    s["bullet"] = ParagraphStyle("dm_bullet", parent=s["body"], leftIndent=13,
                                 bulletIndent=3, spaceAfter=2.5, alignment=TA_LEFT)
    s["quote"] = ParagraphStyle("dm_quote", parent=s["body"], leftIndent=12,
                                rightIndent=8, textColor=MUTED, italic=False,
                                borderPadding=(6, 4, 6, 4), spaceBefore=4, spaceAfter=8,
                                alignment=TA_LEFT)
    s["code"] = ParagraphStyle("dm_code", parent=s["body"], fontName=MONO_FONT,
                               fontSize=8.2, leading=10.8, textColor=INK,
                               leftIndent=8, spaceAfter=6, alignment=TA_LEFT)
    s["caption"] = ParagraphStyle("dm_caption", parent=s["body"], fontSize=8.6,
                                  leading=12, textColor=MUTED, alignment=TA_LEFT,
                                  spaceBefore=3, spaceAfter=10)
    s["figure"] = ParagraphStyle("dm_figure", parent=s["body"], alignment=TA_CENTER,
                                 spaceBefore=6, spaceAfter=2)
    s["toc_title"] = ParagraphStyle(
        "dm_toc_title", parent=s["h1"], fontSize=15, leading=19, spaceAfter=10)
    s["toc"] = ParagraphStyle("dm_toc", parent=s["body"], fontSize=9.2, leading=15,
                              spaceAfter=0, alignment=TA_LEFT)
    return s


BULLETS = ["•", "–", "·"]


def markdown_to_story(md_text, styles, base_dir, cjk_ok, avail_w, avail_h,
                      title_text=None):
    """Parse the supported markdown subset into a flowable list."""
    story = []
    lines = md_text.splitlines()
    i = 0
    n = len(lines)
    seen_title = False
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # fenced code
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            pre = Preformatted("\n".join(buf) or " ", styles["code"],
                               maxLineLength=110)
            story.append(Spacer(1, 2))
            story.append(pre)
            story.append(Spacer(1, 4))
            continue

        # horizontal rule
        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            story.append(Spacer(1, 3))
            from reportlab.platypus import HRFlowable
            story.append(HRFlowable(width="100%", thickness=0.5, color=RULE,
                                    spaceBefore=2, spaceAfter=6))
            i += 1
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and not seen_title:
                seen_title = True
                story.append(Paragraph(inline(text, cjk_ok), styles["title"]))
            elif level == 1:
                story.append(PageBreak())
                story.append(Paragraph(inline(text, cjk_ok), styles["h1"]))
            elif level == 2:
                story.append(Paragraph(inline(text, cjk_ok), styles["h1"]))
            elif level == 3:
                story.append(Paragraph(inline(text, cjk_ok), styles["h2"]))
            elif level == 4:
                story.append(Paragraph(inline(text, cjk_ok), styles["h3"]))
            else:
                story.append(Paragraph(inline(text, cjk_ok), styles["h4"]))
            i += 1
            continue

        # table
        if stripped.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            rows = [split_row(lines[i])]
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            story.append(Spacer(1, 3))
            story.append(make_table(rows, styles, avail_w, cjk_ok))
            story.append(Spacer(1, 7))
            continue

        # blockquote
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            # One <br/> per source line: the header block is a list of
            # independent facts (template, generated, hashes, rows), and running
            # them together into one sentence makes it unreadable.
            text = "<br/>".join(inline(x.strip(), cjk_ok) for x in buf if x.strip())
            q = Paragraph(text or "&nbsp;", styles["quote"])
            q.borderColor = RULE
            q.borderWidth = 0.5
            q.borderLeft = 2.5
            q.backColor = PANEL_BG
            story.append(q)
            continue

        # standalone image paragraph
        solo = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", stripped)
        if solo:
            src = (base_dir / solo.group(2))
            img = place_image(src, solo.group(1), avail_w * 0.97, avail_h * 0.62)
            i += 1
            if img is None:
                story.append(Paragraph(
                    "[figure missing: %s]" % esc(solo.group(2)), styles["caption"]))
            else:
                img.hAlign = "CENTER"
                story.append(img)
                # The alt text stays in the Markdown (it is what GitHub and screen
                # readers show) but is not printed as a caption: the report writer
                # already puts a real caption immediately above the image, and
                # rendering both produced the same sentence twice on every figure.
            continue

        # list block
        if re.match(r"^([-*+]|\d+[.)])\s+", stripped):
            items = []
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
                depth = 0 if indent < 2 else 1
                items.append((depth, mm2.group(1), mm2.group(2)))
                i += 1
            numbered = bool(items) and items[0][1][0].isdigit()
            counters = [0, 0]
            for depth, marker, text in items:
                if numbered:
                    counters[depth] += 1
                    for k in range(depth + 1, 2):
                        counters[k] = 0
                    bullet = "%d." % counters[depth]
                else:
                    bullet = BULLETS[depth]
                st = ParagraphStyle("li%d" % depth, parent=styles["bullet"],
                                    leftIndent=13 + depth * 13, bulletIndent=3 + depth * 13,
                                    firstLineIndent=0)
                story.append(Paragraph(inline(text, cjk_ok), st, bulletText=bullet))
            story.append(Spacer(1, 4))
            continue

        # paragraph
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if not nxt:
                break
            if (re.match(r"^#{1,6}\s", nxt) or nxt.startswith("|")
                    or nxt.startswith(">") or nxt.startswith("```")
                    or re.match(r"^([-*+]|\d+[.)])\s+", nxt)
                    or re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}", nxt)):
                break
            buf.append(nxt)
            i += 1
        story.append(Paragraph(inline(" ".join(buf), cjk_ok), styles["body"]))
    return story


# -------------------------------------------------------------------- doc

class ReportDoc(BaseDocTemplate):
    def __init__(self, path, footer_label, **kw):
        BaseDocTemplate.__init__(self, path, **kw)
        self.footer_label = footer_label

    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        if style in ("dm_h1", "dm_h2", "dm_h3"):
            level = {"dm_h1": 0, "dm_h2": 1, "dm_h3": 2}[style]
            text = flowable.getPlainText()
            self.notify("TOCEntry", (level, text, self.page))

    def on_page(self, canv, doc):
        canv.saveState()
        canv.setFont(BASE_FONT, 7.6)
        canv.setFillColor(MUTED)
        canv.drawString(doc.leftMargin, 11 * mm, self.footer_label)
        canv.drawRightString(A4[0] - doc.rightMargin, 11 * mm, "page %d" % canv.getPageNumber())
        canv.setStrokeColor(RULE)
        canv.setLineWidth(0.4)
        canv.line(doc.leftMargin, 14.5 * mm, A4[0] - doc.rightMargin, 14.5 * mm)
        canv.restoreState()

    def on_page_cover(self, canv, doc):
        canv.saveState()
        canv.setFillColor(ACCENT)
        canv.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, stroke=0, fill=1)
        canv.setFillColor(MUTED)
        canv.setFont(BASE_FONT, 7.6)
        canv.drawString(doc.leftMargin, 11 * mm, self.footer_label)
        canv.drawRightString(A4[0] - doc.rightMargin, 11 * mm, "page %d" % canv.getPageNumber())
        canv.restoreState()


def render(md_path: Path, pdf_path: Path, footer_label: str = "") -> dict:
    cjk_ok = register_fonts()
    md_text = md_path.read_text(encoding="utf-8")
    used_cjk = needs_cjk(md_text)

    left = right = 20 * mm
    top = 20 * mm
    bottom = 18 * mm
    avail_w = A4[0] - left - right
    avail_h = A4[1] - top - bottom

    styles = build_styles()
    story = markdown_to_story(md_text, styles, md_path.parent, used_cjk,
                              avail_w, avail_h)

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc0", fontName=BASE_FONT_BOLD, fontSize=9.8, leading=16,
                       leftIndent=0, firstLineIndent=0, textColor=INK),
        ParagraphStyle("toc1", fontName=BASE_FONT, fontSize=9.0, leading=14,
                       leftIndent=14, firstLineIndent=0, textColor=MUTED),
        ParagraphStyle("toc2", fontName=BASE_FONT, fontSize=8.6, leading=13,
                       leftIndent=28, firstLineIndent=0, textColor=MUTED),
    ]

    # toc_title is deliberately not named dm_h1: afterFlowable() registers every
    # dm_h1 paragraph in the TOC, and the heading "Contents" would then list itself.
    front = [Spacer(1, 6 * mm), Paragraph("Contents", styles["toc_title"]), toc,
             PageBreak()]

    doc = ReportDoc(str(pdf_path), footer_label,
                    pagesize=A4,
                    leftMargin=left, rightMargin=right,
                    topMargin=top, bottomMargin=bottom,
                    title=footer_label or "data-master report",
                    author="data-master",
                    subject="automated statistical report")

    frame_cover = Frame(left, bottom, avail_w, avail_h, id="cover")
    frame_body = Frame(left, bottom, avail_w, avail_h, id="body")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=doc.on_page_cover),
        PageTemplate(id="body", frames=[frame_body], onPage=doc.on_page),
    ])
    doc.multiBuild(front + story)

    return {
        "backend": "reportlab",
        "reportlab_version": _rl_version(),
        "pages": _page_count(pdf_path),
        "bytes": pdf_path.stat().st_size,
        "cjk_font_embedded": bool(used_cjk),
        "cjk_font_available": bool(cjk_ok and used_cjk),
        "cjk_text_present": bool(used_cjk),
    }


def _rl_version():
    try:
        import reportlab
        return getattr(reportlab, "Version", "unknown")
    except Exception:
        return "unknown"


def _page_count(pdf_path: Path) -> int:
    try:
        data = pdf_path.read_bytes()
        m = re.findall(rb"/Type\s*/Page[^s]", data)
        return len(m) or -1
    except Exception:
        return -1


def main() -> int:
    ap = argparse.ArgumentParser(description="markdown -> PDF via reportlab")
    ap.add_argument("--md", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--footer", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    info = render(Path(a.md), Path(a.pdf), a.footer)
    if a.json:
        print(json.dumps(info, indent=2))
    else:
        print("reportlab: %s -> %s (%d bytes, %d pages)"
              % (a.md, a.pdf, info["bytes"], info["pages"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
