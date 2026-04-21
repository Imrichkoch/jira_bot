from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


STOPWORDS = {
    "a",
    "aj",
    "ale",
    "alebo",
    "and",
    "as",
    "at",
    "bez",
    "by",
    "co",
    "do",
    "for",
    "from",
    "i",
    "in",
    "is",
    "je",
    "k",
    "na",
    "o",
    "od",
    "po",
    "pre",
    "s",
    "sa",
    "se",
    "si",
    "so",
    "the",
    "to",
    "u",
    "v",
    "vo",
    "z",
    "za",
    "ze",
}


def extract_adf_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        parts: list[str] = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        content = node.get("content")
        if isinstance(content, list):
            for item in content:
                extracted = extract_adf_text(item)
                if extracted:
                    parts.append(extracted)
        return " ".join(parts).strip()
    if isinstance(node, list):
        return " ".join(extract_adf_text(item) for item in node).strip()
    return ""


def normalize_text(text: str) -> list[str]:
    chunks = re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())
    return [t for t in chunks if t not in STOPWORDS]


def cosine_similarity(a: str, b: str) -> float:
    a_tokens = normalize_text(a)
    b_tokens = normalize_text(b)
    if not a_tokens or not b_tokens:
        return 0.0
    a_vec = Counter(a_tokens)
    b_vec = Counter(b_tokens)
    common = set(a_vec.keys()) & set(b_vec.keys())
    dot = sum(a_vec[t] * b_vec[t] for t in common)
    a_mag = math.sqrt(sum(v * v for v in a_vec.values()))
    b_mag = math.sqrt(sum(v * v for v in b_vec.values()))
    if a_mag == 0 or b_mag == 0:
        return 0.0
    return dot / (a_mag * b_mag)


def overlap_keywords(a: str, b: str, top_n: int = 10) -> list[str]:
    a_set = set(normalize_text(a))
    b_set = set(normalize_text(b))
    overlap = sorted(a_set & b_set)
    return overlap[:top_n]
