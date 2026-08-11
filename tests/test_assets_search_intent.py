from app.main import _assets_aql_hint, _is_available_assets_query


def test_available_laptops_slovak_with_diacritics() -> None:
    assert _is_available_assets_query("Ukáž mi všetky voľné laptopy") is True
    assert _assets_aql_hint("Ukáž mi všetky voľné laptopy") == (
        'objectType = "Laptop" AND Status = "Available"'
    )


def test_available_notebooks_without_diacritics() -> None:
    assert _assets_aql_hint("daj dostupne notebooky") == (
        'objectType = "Laptop" AND Status = "Available"'
    )


def test_general_assets_question_uses_ai_generation() -> None:
    assert _is_available_assets_query("Kto je vlastnik servera DB-01?") is False
    assert _assets_aql_hint("Kto je vlastnik servera DB-01?") is None
