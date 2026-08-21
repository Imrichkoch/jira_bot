from app.main import (
    _assets_aql_hint,
    _extract_onboarding_recipient,
    _is_available_assets_query,
    _is_onboarding_command,
    _optional_asset_status_update,
)


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


def test_onboarding_command_extracts_recipient() -> None:
    assert _extract_onboarding_recipient("onboarding imrich koch") == "imrich koch"


def test_misspelled_onboarding_command_keeps_recipient() -> None:
    assert _is_onboarding_command("onbored imrich koch") is True
    assert _extract_onboarding_recipient("onbored imrich koch") == "imrich koch"


def test_onboarding_preposition_still_extracts_clean_name() -> None:
    assert _extract_onboarding_recipient("onboarding pre imrich koch") == "imrich koch"


def test_optional_status_update_uses_editable_status_attribute() -> None:
    raw_asset = {
        "attributes": [
            {"objectTypeAttribute": {"id": "71", "name": "Status", "editable": True}},
        ]
    }
    assert _optional_asset_status_update(raw_asset, "In use") == {
        "objectTypeAttributeId": "71",
        "objectAttributeValues": [{"value": "In use"}],
    }
