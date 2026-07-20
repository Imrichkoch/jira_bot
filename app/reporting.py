from __future__ import annotations

import html
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


def _report_spec(message: str) -> tuple[str, str, int | None]:
    text = message.lower()
    if re.search(r"(priorit|priority)", text):
        kind, title = "priority", "Tickets by priority"
    elif re.search(r"(assignee|assigned|priraden|pouzivatel|používateľ|user)", text):
        kind, title = "assignee", "Tickets by assignee"
    elif re.search(r"(type|typ ticket|typ tiket|issue type)", text):
        kind, title = "issue_type", "Tickets by type"
    elif re.search(r"(trend|created|vytvoren|tyzden|týždeň|month|mesiac)", text):
        kind, title = "created_trend", "Created tickets over time"
    else:
        kind, title = "status", "Tickets by status"
    period = re.search(r"(?:last|za posledn)[^0-9]{0,12}(7|14|30|60|90)\s*(?:d|day|dni)", text)
    return kind, title, int(period.group(1)) if period else None


def _label(issue: dict, kind: str) -> str:
    fields = issue.get("fields") or {}
    if kind == "priority":
        return str((fields.get("priority") or {}).get("name") or "No priority")
    if kind == "assignee":
        return str((fields.get("assignee") or {}).get("displayName") or "Unassigned")
    if kind == "issue_type":
        return str((fields.get("issuetype") or {}).get("name") or "Unknown")
    if kind == "created_trend":
        value = str(fields.get("created") or "")
        return value[:10] if len(value) >= 10 else "Unknown date"
    return str((fields.get("status") or {}).get("name") or "Unknown")


def _svg(title: str, counts: list[tuple[str, int]]) -> str:
    width, height, left, bottom = 860, 430, 80, 90
    chart_height = 270
    top = 65
    maximum = max([value for _, value in counts] or [1])
    slot = (width - left - 30) / max(len(counts), 1)
    bars: list[str] = []
    for index, (label, value) in enumerate(counts):
        bar_width = min(64, slot * 0.62)
        x = left + index * slot + (slot - bar_width) / 2
        bar_height = max(3, chart_height * value / maximum)
        y = top + chart_height - bar_height
        safe_label = html.escape(label[:20])
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" rx="5" fill="#0c66e4"/>'
            f'<text x="{x + bar_width / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" class="value">{value}</text>'
            f'<text x="{x + bar_width / 2:.1f}" y="{top + chart_height + 24:.1f}" text-anchor="middle" class="label">{safe_label}</text>'
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>.title{{font:700 22px Arial;fill:#172b4d}}.label{{font:12px Arial;fill:#44546f}}.value{{font:700 13px Arial;fill:#172b4d}}.axis{{stroke:#dfe1e6;stroke-width:2}}</style>
<rect width="100%" height="100%" fill="#ffffff"/><text x="{left}" y="36" class="title">{html.escape(title)}</text>
<line x1="{left}" y1="{top + chart_height}" x2="{width - 30}" y2="{top + chart_height}" class="axis"/>{''.join(bars)}
</svg>'''


def _write_pdf(path: Path, title: str, counts: list[tuple[str, int]], total: int) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    page_width, page_height = A4
    pdf.setFillColor(HexColor("#172B4D"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, page_height - 58, "JiraBot Report")
    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(HexColor("#44546F"))
    pdf.drawString(48, page_height - 78, title)
    pdf.drawRightString(page_width - 48, page_height - 78, f"Total tickets: {total}")
    maximum = max([value for _, value in counts] or [1])
    y = page_height - 125
    for label, value in counts[:18]:
        pdf.setFillColor(HexColor("#172B4D"))
        pdf.setFont("Helvetica", 10)
        pdf.drawString(48, y + 3, label[:48])
        bar_width = 300 * value / maximum
        pdf.setFillColor(HexColor("#0C66E4"))
        pdf.roundRect(205, y, bar_width, 14, 3, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#172B4D"))
        pdf.drawString(515, y + 3, str(value))
        y -= 24
        if y < 60:
            pdf.showPage()
            y = page_height - 60
    pdf.save()


def _write_xlsx(path: Path, title: str, counts: list[tuple[str, int]]) -> None:
    # XLSX is a ZIP of XML files; this avoids another runtime dependency.
    rows = [("Category", "Tickets"), *counts]
    sheet_rows = []
    for index, (label, value) in enumerate(rows, start=1):
        sheet_rows.append(
            f'<row r="{index}"><c r="A{index}" t="inlineStr"><is><t>{xml_escape(str(label))}</t></is></c>'
            f'<c r="B{index}" t="n"><v>{value if index > 1 else 0}</v></c></row>'
        )
    content_types = '''<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    workbook = f'''<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''
    sheet = f'''<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{''.join(sheet_rows)}</sheetData></worksheet>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def build_ticket_report(jira, project_key: str, message: str, output_dir: Path) -> dict:
    kind, title, days = _report_spec(message)
    jql = f"project = {project_key}"
    if days:
        jql += f" AND created >= -{days}d"
    jql += " ORDER BY created DESC"
    result = jira.search_with_fields(
        jql=jql,
        fields=["summary", "status", "priority", "assignee", "created", "updated", "issuetype"],
        max_results=500,
    )
    issues = result.get("issues") or []
    counts = Counter(_label(issue, kind) for issue in issues)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:20]
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = f"jira-report-{kind}-{stamp}"
    svg_name, pdf_name, xlsx_name = f"{stem}.svg", f"{stem}.pdf", f"{stem}.xlsx"
    (output_dir / svg_name).write_text(_svg(title, ordered), encoding="utf-8")
    _write_pdf(output_dir / pdf_name, title, ordered, len(issues))
    _write_xlsx(output_dir / xlsx_name, title, ordered)
    return {"title": title, "kind": kind, "jql": jql, "total": len(issues), "counts": [{"label": label, "value": value} for label, value in ordered], "files": {"chart": svg_name, "pdf": pdf_name, "xlsx": xlsx_name}}
