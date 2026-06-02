#!/usr/bin/env python3
"""Create a simple PDF copy of bingo_report.md."""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = ROOT / "report" / "bingo_report.md"
REPORT_PDF = ROOT / "report" / "bingo_report.pdf"


def paragraph_for_line(line, styles):
    stripped = line.strip()
    if not stripped:
        return Spacer(1, 4)
    if stripped.startswith("# "):
        return Paragraph(stripped[2:], styles["Title"])
    if stripped.startswith("## "):
        return Paragraph(stripped[3:], styles["Heading1"])
    if stripped.startswith("### "):
        return Paragraph(stripped[4:], styles["Heading2"])
    if stripped.startswith("- "):
        return Paragraph("&bull; " + stripped[2:], styles["BodyText"])
    if stripped.startswith("![") and "](" in stripped and stripped.endswith(")"):
        image_path = REPORT_MD.parent / stripped.split("](", 1)[1][:-1]
        if image_path.exists():
            return Image(str(image_path), width=6.2 * inch, height=2.70 * inch)
    if stripped.startswith("```"):
        return Spacer(1, 4)
    return Paragraph(stripped.replace("`", ""), styles["BodyText"])


def main():
    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 16
    styles["Title"].leading = 18
    styles["Title"].spaceAfter = 6
    styles["Heading1"].fontSize = 12
    styles["Heading1"].leading = 14
    styles["Heading1"].spaceBefore = 5
    styles["Heading1"].spaceAfter = 2
    styles["BodyText"].fontSize = 8.5
    styles["BodyText"].leading = 10.5
    doc = SimpleDocTemplate(
        str(REPORT_PDF),
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
    )
    story = []
    for line in REPORT_MD.read_text(encoding="utf-8").splitlines():
        story.append(paragraph_for_line(line, styles))
    doc.build(story)
    print(REPORT_PDF)


if __name__ == "__main__":
    main()
