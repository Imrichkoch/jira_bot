from app.error_messages import friendly_error_message


ASSETS_403 = "Jira Assets API error: {'status_code': 403, 'body': 'Access to Assets API was denied'}"


def test_assets_permission_error_uses_slovak_for_slovak_request():
    message = friendly_error_message(ASSETS_403, "onborduj imrich koch")
    assert message.startswith("Jira token funguje")
    assert "Object Schema Manager" in message


def test_assets_permission_error_keeps_english_for_english_request():
    message = friendly_error_message(ASSETS_403, "onboard Imrich Koch")
    assert message.startswith("The Jira API token works")
