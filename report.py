#!/usr/bin/env python3
"""
Turns output/results.json (produced by run.py) into a readable PDF report -
one section per portfolio, with holdings, allocation, and insights as tables
rather than a wall of text.

Usage:
    python run.py                          # produces output/results.json
    python report.py                       # produces output/portfolio_report.pdf
    python report.py --in path/to/results.json --out path/to/report.pdf
"""
import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)

BASE = Path(__file__).parent

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1", parent=styles["Heading1"], spaceAfter=4, textColor=colors.HexColor("#1a2b4c")))
styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1a2b4c")))
styles.add(ParagraphStyle(name="Meta", parent=styles["Normal"], textColor=colors.HexColor("#555555"), fontSize=9))
styles.add(ParagraphStyle(name="InsightTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10.5))
styles.add(ParagraphStyle(name="Body", parent=styles["Normal"], fontSize=9.5, leading=13))
styles.add(ParagraphStyle(name="Disclaimer", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#777777")))
styles.add(ParagraphStyle(name="Warning", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#a94442")))
styles.add(ParagraphStyle(name="Cell", parent=styles["Normal"], fontSize=8.5, leading=10.5))
styles.add(ParagraphStyle(name="CellBold", parent=styles["Cell"], fontName="Helvetica-Bold"))

TABLE_HEADER_BG = colors.HexColor("#1a2b4c")
TABLE_ALT_BG = colors.HexColor("#f2f5fa")
PRIORITY_BG = colors.HexColor("#e8edf7")


def money(v):
    return f"Rs {v:,.0f}" if isinstance(v, (int, float)) else str(v)


def pct(v):
    return f"{v:.2f}%" if isinstance(v, (int, float)) else "-"


# Result words worth calling out visually in the PDF - longest phrases first
# so "very high" matches before the bare "high" inside it does.
_HIGHLIGHT_PHRASES = [
    "very high", "moderately high", "moderately low", "moderate",
    "high", "low", "mismatch", "aligned",
]
_HIGHLIGHT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _HIGHLIGHT_PHRASES) + r")\b",
    re.IGNORECASE,
)


def highlight(text: str) -> str:
    """
    Escapes text for safe use inside a ReportLab Paragraph, then underlines
    and bolds the key result word (high/low/moderate/mismatch/aligned/etc.)
    so the main takeaway is visible at a glance rather than buried in prose.
    """
    escaped = escape(str(text))
    return _HIGHLIGHT_PATTERN.sub(lambda m: f"<u><b>{m.group(0)}</b></u>", escaped)


def category_label(category: str) -> str:
    return category.replace("_", " ").title()


def cell(text):
    """Wrap text in a Paragraph so it word-wraps inside a table column instead of overflowing.
    Escapes first since table cell values can come from investor-supplied scheme names."""
    return Paragraph(escape(str(text)), styles["Cell"])


def styled_table(data, col_widths, align_right_cols=(), header_is_plain=True):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for r in range(1, len(data)):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), TABLE_ALT_BG))
    for c in align_right_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def build_rejected_section(result):
    elems = [Paragraph(f"{escape(result['portfolio_no'])}  -  REJECTED", styles["H1"])]
    elems.append(Paragraph(escape(result["reason"]), styles["Body"]))
    errs = result.get("validation_errors", [])
    if errs:
        rows = [["Field", "Problem"]]
        for e in errs:
            field = ".".join(str(x) for x in e.get("loc", []))
            rows.append([cell(field), cell(e.get("msg", ""))])
        elems.append(Spacer(1, 4))
        elems.append(styled_table(rows, [50 * mm, 110 * mm]))
    return elems


def build_portfolio_section(result):
    eb = result["evidence_bundle"]
    out = result["insight_output"]
    elems = []

    elems.append(Paragraph(f"{escape(eb['portfolio_no'])}  -  {escape(eb['investor_name'])}", styles["H1"]))
    elems.append(Paragraph(
        f"Age {eb['age']}  |  Goal: {escape(eb['goal'])}  |  Horizon: {eb['horizon_years']} years  |  "
        f"Risk appetite: {escape(eb['risk_appetite'])}  |  Monthly capacity: {money(eb['monthly_investment_capacity'])}",
        styles["Meta"]))
    elems.append(Spacer(1, 6))

    # --- Holdings table ---
    elems.append(Paragraph("Holdings", styles["H2"]))
    rows = [["Scheme", "Category", "Weight", "Invested", "Market Value", "Gain", "XIRR", "Risk"]]
    for h in eb["holdings"]:
        xirr_txt = pct(h["xirr_pct"]) if h["xirr_pct"] is not None else "n/a"
        risk_txt = h["risk_grade"] or "unavailable"
        rows.append([
            cell(h["scheme_name"]), cell(h["category"]), cell(pct(h["weight_pct"])),
            cell(money(h["invested_amount"])), cell(money(h["market_value"])),
            cell(pct(h["gain_pct"])), cell(xirr_txt), cell(risk_txt),
        ])
    elems.append(styled_table(
        rows,
        [48 * mm, 27 * mm, 14 * mm, 21 * mm, 21 * mm, 14 * mm, 14 * mm, 20 * mm],
        align_right_cols=(),
    ))

    # --- Portfolio-level metrics ---
    elems.append(Paragraph("Portfolio Metrics", styles["H2"]))
    r = eb["portfolio_returns"]
    c = eb["concentration"]
    metrics_rows = [
        ["Metric", "Value"],
        [cell("Total invested"), cell(money(r["total_invested"]))],
        [cell("Total market value"), cell(money(r["total_market_value"]))],
        [cell("Absolute gain"), cell(f"{money(r['absolute_gain'])}  ({pct(r['absolute_gain_pct'])})")],
        [cell("Portfolio XIRR"), cell(pct(r["portfolio_xirr_pct"]) if r["portfolio_xirr_pct"] is not None else "n/a - " + (r.get("xirr_note") or ""))],
        [cell("Concentration (HHI)"), cell(f"{c['hhi']}  ({c['hhi_interpretation']})")],
        [cell("Largest single holding"), cell(f"{c['top_holding_name']}  -  {pct(c['top_holding_weight_pct'])}")],
    ]
    elems.append(styled_table(metrics_rows, [55 * mm, 115 * mm]))

    # --- Insights ---
    elems.append(Paragraph("Key Insights", styles["H2"]))
    for ins in out["insights"]:
        header_text = f"{ins['priority']}. {category_label(ins['category'])} - {highlight(ins['title'])}"
        block = [
            Paragraph(header_text, styles["InsightTitle"]),
            Paragraph(highlight(ins["explanation"]), styles["Body"]),
            Spacer(1, 6),
        ]
        elems.append(KeepTogether(block))

    # --- Warnings ---
    if out.get("warnings"):
        elems.append(Paragraph("System Warnings", styles["H2"]))
        for w in out["warnings"]:
            elems.append(Paragraph(f"&#9888; {escape(w)}", styles["Warning"]))
        elems.append(Spacer(1, 4))

    # --- Disclaimer ---
    elems.append(Spacer(1, 8))
    elems.append(Paragraph(escape(out["disclaimer"]), styles["Disclaimer"]))

    return elems


def build_report(results: list[dict], out_path: str):
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
    )
    story = []

    story.append(Paragraph("Mutual Fund Portfolio Intelligence Report", styles["Title"]))
    story.append(Spacer(1, 10))

    for i, result in enumerate(results):
        if result["status"] == "rejected":
            section = build_rejected_section(result)
        else:
            section = build_portfolio_section(result)
        story.extend(section)
        if i < len(results) - 1:
            story.append(PageBreak())

    doc.build(story)


def main():
    ap = argparse.ArgumentParser(description="Render results.json as a tabular PDF report")
    ap.add_argument("--in", dest="in_path", default=str(BASE / "output" / "results.json"))
    ap.add_argument("--out", dest="out_path", default=str(BASE / "output" / "portfolio_report.pdf"))
    args = ap.parse_args()

    with open(args.in_path) as f:
        results = json.load(f)

    Path(args.out_path).parent.mkdir(parents=True, exist_ok=True)
    build_report(results, args.out_path)
    print(f"PDF report written to {args.out_path}")


if __name__ == "__main__":
    main()
