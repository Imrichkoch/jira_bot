import base64
import tempfile
from pathlib import Path

from app.rag_store import RagStore


def test_rag_returns_relevant_uploaded_text():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = RagStore(Path(temp_dir))
        store.add_document(
            name="VPN knowledge base",
            file_name="vpn.md",
            content_base64=base64.b64encode(
                b"VPN access requires MFA. Reset the VPN profile before escalating a connection issue."
            ).decode(),
        )
        matches = store.retrieve("How do I reset VPN access?", limit=3)
        assert len(matches) == 1
        assert matches[0]["document_name"] == "VPN knowledge base"
        assert "MFA" in matches[0]["text"]

