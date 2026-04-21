import re


class JQLValidationError(ValueError):
    pass


def validate_jql(jql: str, max_len: int = 600) -> str:
    normalized = " ".join(jql.strip().split())
    if normalized.lower().startswith("jql:"):
        normalized = normalized[4:].strip()
    normalized = normalized.replace("\\(", "(").replace("\\)", ")").rstrip(";")
    if not normalized:
        raise JQLValidationError("JQL is empty.")
    if len(normalized) > max_len:
        raise JQLValidationError("JQL is too long.")

    forbidden_tokens = [";", "--", "/*", "*/", " drop ", " delete ", " update ", " insert ", " alter "]
    lowered = f" {normalized.lower()} "
    if any(token in lowered for token in forbidden_tokens):
        raise JQLValidationError("JQL contains forbidden tokens.")

    if not re.search(r"\bproject\s*=", normalized, flags=re.IGNORECASE):
        raise JQLValidationError("JQL must include explicit project filter.")

    # Guard against malformed ORDER BY fragments from model output.
    order_by_match = re.search(r"\border\s+by\b", normalized, flags=re.IGNORECASE)
    if order_by_match:
        prefix = normalized[: order_by_match.start()].strip()
        order_part = normalized[order_by_match.start() :].strip()
        m = re.match(r"(?i)^order\s+by\s+([a-zA-Z][\w\.]*)(?:\s+(asc|desc))?$", order_part)
        if not m:
            normalized = f"{prefix} ORDER BY updated DESC".strip()
        elif m.group(2) is None:
            normalized = f"{prefix} ORDER BY {m.group(1)} DESC".strip()

    return normalized
