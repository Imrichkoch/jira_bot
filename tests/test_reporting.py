import tempfile
import zipfile
from pathlib import Path

from app.reporting import build_ticket_report


class FakeJira:
    def search_with_fields(self, **_kwargs):
        return {
            "issues": [
                {"fields": {"status": {"name": "Open"}, "priority": {"name": "High"}, "created": "2026-07-20T10:00:00Z"}},
                {"fields": {"status": {"name": "Open"}, "priority": {"name": "Medium"}, "created": "2026-07-19T10:00:00Z"}},
                {"fields": {"status": {"name": "Done"}, "priority": {"name": "High"}, "created": "2026-07-19T11:00:00Z"}},
            ]
        }


def test_priority_report_generates_all_downloads():
    with tempfile.TemporaryDirectory() as temp_dir:
        result = build_ticket_report(FakeJira(), "KAN", "create a chart of tickets by priority", Path(temp_dir))
        assert result["kind"] == "priority"
        assert result["total"] == 3
        assert result["counts"] == [{"label": "High", "value": 2}, {"label": "Medium", "value": 1}]
        assert (Path(temp_dir) / result["files"]["chart"]).read_text(encoding="utf-8").startswith("<svg")
        assert (Path(temp_dir) / result["files"]["pdf"]).read_bytes().startswith(b"%PDF")
        with zipfile.ZipFile(Path(temp_dir) / result["files"]["xlsx"]) as workbook:
            assert "xl/worksheets/sheet1.xml" in workbook.namelist()

