from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pypdf import PdfReader


class RagStore:
    """Small local RAG index using lexical retrieval, with no extra cloud dependency."""

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".pdf", ".docx", ".pptx", ".xlsx"}
    MAX_FILE_BYTES = 16 * 1024 * 1024
    MAX_EXTRACTED_CHARS = 300_000

    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "rag"
        self._files = self._root / "files"
        self._index = self._root / "index.json"
        self._files.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self._index.exists():
            return []
        try:
            data = json.loads(self._index.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self._index.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-zA-Z0-9À-ž_-]{3,}", text.lower())}

    @staticmethod
    def _chunks(text: str, size: int = 1200, overlap: int = 180) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []
        result = []
        start = 0
        while start < len(cleaned):
            end = min(len(cleaned), start + size)
            if end < len(cleaned):
                boundary = cleaned.rfind(" ", start + size // 2, end)
                if boundary > start:
                    end = boundary
            result.append(cleaned[start:end].strip())
            if end >= len(cleaned):
                break
            start = max(end - overlap, start + 1)
        return result

    @staticmethod
    def _zip_text(path: Path, names: list[str]) -> str:
        pieces: list[str] = []
        with zipfile.ZipFile(path) as archive:
            for name in names:
                if name not in archive.namelist():
                    continue
                try:
                    root = ElementTree.fromstring(archive.read(name))
                    pieces.extend(node.text or "" for node in root.iter() if node.text)
                except ElementTree.ParseError:
                    continue
        return " ".join(pieces)

    def _extract_text(self, path: Path, extension: str) -> str:
        if extension in {".txt", ".md", ".csv", ".json", ".log"}:
            return path.read_text(encoding="utf-8", errors="replace")
        if extension == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if extension == ".docx":
            return self._zip_text(path, ["word/document.xml"])
        if extension == ".pptx":
            with zipfile.ZipFile(path) as archive:
                names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            return self._zip_text(path, names)
        if extension == ".xlsx":
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if name.startswith("xl/") and name.endswith(".xml")]
            return self._zip_text(path, names)
        raise ValueError("Unsupported file type.")

    def list_documents(self) -> list[dict[str, Any]]:
        return [{key: value for key, value in item.items() if key != "chunks"} for item in self._load()]

    def add_document(self, *, name: str, file_name: str, content_base64: str) -> dict[str, Any]:
        safe_name = Path(file_name).name
        extension = Path(safe_name).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError("Supported files: TXT, MD, CSV, JSON, LOG, PDF, DOCX, PPTX, XLSX.")
        try:
            if "," in content_base64 and content_base64.lstrip().startswith("data:"):
                content_base64 = content_base64.split(",", 1)[1]
            raw = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid file content.") from exc
        if not raw or len(raw) > self.MAX_FILE_BYTES:
            raise ValueError("File must be between 1 byte and 16 MB.")
        document_id = uuid.uuid4().hex
        stored_name = f"{document_id}{extension}"
        target = self._files / stored_name
        target.write_bytes(raw)
        try:
            text = self._extract_text(target, extension)[: self.MAX_EXTRACTED_CHARS]
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise ValueError(f"Could not read text from this file: {exc}") from exc
        chunks = self._chunks(text)
        if not chunks:
            target.unlink(missing_ok=True)
            raise ValueError("No readable text was found in the file.")
        item = {
            "id": document_id,
            "name": name.strip() or safe_name,
            "file_name": safe_name,
            "extension": extension.lstrip("."),
            "size_bytes": len(raw),
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
        items = self._load()
        items.append(item)
        self._save(items)
        return {key: value for key, value in item.items() if key != "chunks"}

    def delete_document(self, document_id: str) -> None:
        items = self._load()
        kept = [item for item in items if item.get("id") != document_id]
        if len(kept) == len(items):
            raise ValueError("RAG document not found.")
        removed = next(item for item in items if item.get("id") == document_id)
        extension = "." + str(removed.get("extension") or "")
        (self._files / f"{document_id}{extension}").unlink(missing_ok=True)
        self._save(kept)

    def retrieve(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        matches: list[dict[str, Any]] = []
        for document in self._load():
            for chunk in document.get("chunks") or []:
                chunk_tokens = self._tokens(chunk)
                overlap = query_tokens & chunk_tokens
                if not overlap:
                    continue
                score = len(overlap) / max(len(query_tokens), 1) + len(overlap) / max(len(chunk_tokens), 1)
                matches.append({"document_id": document["id"], "document_name": document["name"], "text": chunk, "score": round(score, 4)})
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[: max(1, min(limit, 8))]

    def context_for(self, query: str) -> tuple[str, list[dict[str, str]]]:
        matches = self.retrieve(query)
        if not matches:
            return "", []
        excerpts = []
        sources = []
        for item in matches:
            excerpts.append(f"[Source: {item['document_name']}]\n{item['text']}")
            sources.append({"document_id": item["document_id"], "document_name": item["document_name"]})
        return "\n\n".join(excerpts)[:6000], sources
