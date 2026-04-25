from __future__ import annotations

import base64
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from html import escape as xml_escape
from io import BytesIO
from pathlib import Path
from typing import Any


FIELD_DEFAULTS: dict[str, dict[str, Any]] = {
    "employee_name": {
        "label": "Meno zamestnanca",
        "placeholder": "{{employee_name}}",
        "page": 1,
        "x_pct": 12,
        "y_pct": 24,
        "font_size": 11,
    },
    "device_name": {
        "label": "PC / zariadenie",
        "placeholder": "{{device_name}}",
        "page": 1,
        "x_pct": 12,
        "y_pct": 34,
        "font_size": 11,
    },
    "serial_number": {
        "label": "Seriove cislo",
        "placeholder": "{{serial_number}}",
        "page": 1,
        "x_pct": 12,
        "y_pct": 44,
        "font_size": 11,
    },
    "extra_text": {
        "label": "Doplnujuci text",
        "placeholder": "{{extra_text}}",
        "page": 1,
        "x_pct": 12,
        "y_pct": 54,
        "font_size": 11,
    },
}


def _safe_slug(value: str, fallback: str = "file") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return slug[:120] or fallback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_format(file_name: str, requested: str | None = None) -> str:
    fmt = (requested or "").strip().lower().lstrip(".")
    if not fmt:
        fmt = Path(file_name).suffix.lower().lstrip(".")
    if fmt not in {"docx", "pdf"}:
        raise ValueError("Supported template formats are docx and pdf.")
    return fmt


def _merge_fields(fields: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    merged = json.loads(json.dumps(FIELD_DEFAULTS))
    for key, cfg in (fields or {}).items():
        if key not in merged or not isinstance(cfg, dict):
            continue
        merged[key].update({k: v for k, v in cfg.items() if v is not None})
    return merged


class OffboardingTemplateStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "offboarding_templates"
        self._files_dir = self._root / "files"
        self._meta_path = self._root / "templates.json"
        self._files_dir.mkdir(parents=True, exist_ok=True)
        if not self._meta_path.exists():
            self._write({"templates": []})

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"templates": []}
        if not isinstance(data, dict) or not isinstance(data.get("templates"), list):
            return {"templates": []}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_templates(self) -> list[dict[str, Any]]:
        templates = self._read()["templates"]
        return sorted(templates, key=lambda t: str(t.get("created_at") or ""), reverse=True)

    def get(self, template_id: str) -> dict[str, Any] | None:
        for template in self._read()["templates"]:
            if template.get("id") == template_id:
                return template
        return None

    def active(self) -> dict[str, Any] | None:
        templates = self.list_templates()
        for template in templates:
            if template.get("active"):
                return template
        return templates[0] if templates else None

    def add_template(
        self,
        *,
        name: str,
        file_name: str,
        content_base64: str,
        template_format: str | None,
        fields: dict[str, Any] | None,
        active: bool,
    ) -> dict[str, Any]:
        fmt = _normalize_format(file_name, template_format)
        raw = base64.b64decode(content_base64.split(",", 1)[-1], validate=False)
        if not raw:
            raise ValueError("Template file is empty.")
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Template file is too large. Limit is 8 MB.")

        template_id = uuid.uuid4().hex
        safe_name = _safe_slug(file_name, f"template.{fmt}")
        stored_name = f"{template_id}-{safe_name}"
        stored_path = self._files_dir / stored_name
        stored_path.write_bytes(raw)

        data = self._read()
        if active or not data["templates"]:
            for item in data["templates"]:
                item["active"] = False

        template = {
            "id": template_id,
            "name": name.strip() or Path(file_name).stem,
            "file_name": file_name,
            "stored_file": stored_name,
            "template_format": fmt,
            "fields": _merge_fields(fields),
            "active": bool(active or not data["templates"]),
            "created_at": _now(),
        }
        data["templates"].append(template)
        self._write(data)
        return template

    def set_active(self, template_id: str) -> dict[str, Any]:
        data = self._read()
        selected = None
        for item in data["templates"]:
            item["active"] = item.get("id") == template_id
            if item["active"]:
                selected = item
        if not selected:
            raise ValueError("Template not found.")
        self._write(data)
        return selected

    def update_fields(self, template_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        selected = None
        for item in data["templates"]:
            if item.get("id") == template_id:
                item["fields"] = _merge_fields(fields)
                selected = item
                break
        if not selected:
            raise ValueError("Template not found.")
        self._write(data)
        return selected

    def delete(self, template_id: str) -> None:
        data = self._read()
        kept = []
        removed = None
        for item in data["templates"]:
            if item.get("id") == template_id:
                removed = item
            else:
                kept.append(item)
        if not removed:
            raise ValueError("Template not found.")
        stored_file = removed.get("stored_file")
        if stored_file:
            try:
                (self._files_dir / str(stored_file)).unlink()
            except FileNotFoundError:
                pass
        if kept and not any(item.get("active") for item in kept):
            kept[0]["active"] = True
        data["templates"] = kept
        self._write(data)

    def file_path(self, template: dict[str, Any]) -> Path:
        return self._files_dir / str(template["stored_file"])


def _docx_replacement_value(value: str) -> str:
    escaped = xml_escape(value or "", quote=False)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "</w:t><w:br/><w:t>")


def render_docx_template(template_path: Path, output_path: Path, values: dict[str, str], fields: dict[str, Any]) -> None:
    merged_fields = _merge_fields(fields)
    with zipfile.ZipFile(template_path, "r") as zin, zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                for key, cfg in merged_fields.items():
                    placeholder = str(cfg.get("placeholder") or FIELD_DEFAULTS[key]["placeholder"])
                    replacement = _docx_replacement_value(values.get(key, ""))
                    text = text.replace(xml_escape(placeholder, quote=False), replacement)
                    text = text.replace(placeholder, replacement)
                data = text.encode("utf-8")
            zout.writestr(item, data)


def _wrap_text(value: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for raw_line in (value or "").splitlines() or [""]:
        words = raw_line.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def _draw_pdf_values(canvas_obj: Any, *, width: float, height: float, values: dict[str, str], fields: dict[str, Any], page: int) -> None:
    merged_fields = _merge_fields(fields)
    for key, cfg in merged_fields.items():
        if int(cfg.get("page") or 1) != page:
            continue
        value = values.get(key, "")
        if not value:
            continue
        font_size = float(cfg.get("font_size") or 11)
        x = (float(cfg.get("x_pct") or 0) / 100.0) * width
        y = height - ((float(cfg.get("y_pct") or 0) / 100.0) * height)
        canvas_obj.setFont("Helvetica", font_size)
        max_chars = max(20, int((width - x - 36) / max(font_size * 0.55, 4)))
        line_height = font_size + 3
        for line in _wrap_text(str(value), max_chars):
            canvas_obj.drawString(x, y, line)
            y -= line_height


def render_pdf_template(template_path: Path, output_path: Path, values: dict[str, str], fields: dict[str, Any]) -> None:
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    for index, page_obj in enumerate(reader.pages):
        width = float(page_obj.mediabox.width)
        height = float(page_obj.mediabox.height)
        packet = BytesIO()
        overlay_canvas = canvas.Canvas(packet, pagesize=(width, height))
        _draw_pdf_values(overlay_canvas, width=width, height=height, values=values, fields=fields, page=index + 1)
        overlay_canvas.showPage()
        overlay_canvas.save()
        packet.seek(0)
        overlay_pdf = PdfReader(packet)
        page_obj.merge_page(overlay_pdf.pages[0])
        writer.add_page(page_obj)
    with output_path.open("wb") as fh:
        writer.write(fh)


def render_default_pdf(output_path: Path, values: dict[str, str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4
    y = height - 70
    c.setFont("Helvetica-Bold", 18)
    c.drawString(56, y, "Offboarding - odovzdanie zariadenia")
    y -= 42
    c.setFont("Helvetica", 11)
    for label, key in [
        ("Meno", "employee_name"),
        ("PC / zariadenie", "device_name"),
        ("Seriove cislo", "serial_number"),
        ("Doplnujuci text", "extra_text"),
    ]:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(56, y, f"{label}:")
        y -= 16
        c.setFont("Helvetica", 11)
        for line in _wrap_text(values.get(key, ""), 90):
            c.drawString(76, y, line)
            y -= 15
        y -= 8
    c.line(56, 155, width - 56, 155)
    c.drawString(56, 120, "Odovzdal: ____________________")
    c.drawString(330, 120, "Prevzal: ____________________")
    c.drawString(56, 88, "Datum: ____________________")
    c.save()


def render_offboarding_document(
    *,
    template_store: OffboardingTemplateStore,
    template: dict[str, Any] | None,
    output_dir: Path,
    values: dict[str, str],
    file_stem: str,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not template:
        file_name = f"{_safe_slug(file_stem)}.pdf"
        output_path = output_dir / file_name
        render_default_pdf(output_path, values)
        return {"file_name": file_name, "format": "pdf"}

    fmt = str(template.get("template_format") or "pdf").lower()
    file_name = f"{_safe_slug(file_stem)}.{fmt}"
    output_path = output_dir / file_name
    template_path = template_store.file_path(template)
    fields = template.get("fields") or {}
    if fmt == "docx":
        render_docx_template(template_path, output_path, values, fields)
    elif fmt == "pdf":
        render_pdf_template(template_path, output_path, values, fields)
    else:
        raise ValueError("Unsupported template format.")
    return {"file_name": file_name, "format": fmt}
