import base64
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.offboarding_documents import OffboardingTemplateStore, render_offboarding_document


def test_docx_template_generates_pdf_output():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = OffboardingTemplateStore(root)
        template = store.add_template(
            name="Word handover",
            file_name="handover.docx",
            content_base64=base64.b64encode(b"test-docx-content").decode("ascii"),
            template_format="docx",
            fields={},
            active=True,
        )

        with patch("app.offboarding_documents.render_docx_as_pdf_template") as render_pdf:
            render_pdf.side_effect = lambda _source, output, _values, _fields: output.write_bytes(b"%PDF-test")
            result = render_offboarding_document(
                template_store=store,
                template=template,
                output_dir=root / "generated",
                values={"employee_name": "Test User"},
                file_stem="handover-test",
            )

        assert result == {"file_name": "handover-test.pdf", "format": "pdf"}
        assert (root / "generated" / "handover-test.pdf").read_bytes().startswith(b"%PDF")
        render_pdf.assert_called_once()
