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


class LocalizedFakeJira:
    def search_with_fields(self, **_kwargs):
        return {
            "issues": [
                {"fields": {"status": {"name": "Úlohy"}}},
                {"fields": {"status": {"name": "Vyriešené"}}},
                {"fields": {"status": {"name": "Rozpracované"}}},
                {"fields": {"status": {"name": "Waiting for customer"}}},
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


def test_status_report_uses_english_labels_by_default():
    with tempfile.TemporaryDirectory() as temp_dir:
        result = build_ticket_report(LocalizedFakeJira(), "KAN", "tickets by status", Path(temp_dir))

        assert result["title"] == "Tickets by status"
        assert result["counts"] == [
            {"label": "In Progress", "value": 1},
            {"label": "Resolved", "value": 1},
            {"label": "Tasks", "value": 1},
            {"label": "Waiting for customer", "value": 1},
        ]
        svg = (Path(temp_dir) / result["files"]["chart"]).read_text(encoding="utf-8")
        assert "Vyriešené" not in svg
        assert "Rozpracované" not in svg
        assert "Resolved" in svg
        assert "In Progress" in svg


def test_report_prefers_atlassian_untranslated_name():
    class JiraWithUntranslatedStatus:
        def search_with_fields(self, **_kwargs):
            return {
                "issues": [
                    {
                        "fields": {
                            "status": {
                                "name": "Vlastný slovenský stav",
                                "untranslatedName": "Custom English status",
                            }
                        }
                    }
                ]
            }

    with tempfile.TemporaryDirectory() as temp_dir:
        result = build_ticket_report(JiraWithUntranslatedStatus(), "KAN", "tickets by status", Path(temp_dir))
        assert result["counts"] == [{"label": "Custom English status", "value": 1}]
