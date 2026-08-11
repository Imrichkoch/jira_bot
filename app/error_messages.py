from __future__ import annotations

import re
import unicodedata


def _looks_slovak(message: str) -> bool:
    normalized = unicodedata.normalize("NFKD", (message or "").lower()).encode("ascii", "ignore").decode("ascii")
    words = set(re.findall(r"[a-z]+", normalized))
    slovak_markers = {
        "aky", "ake", "ano", "daj", "komu", "mne", "najdi", "onboarduj", "onborduj", "pre",
        "prirad", "prosim", "sprav", "ticket", "uzavri", "vytvor", "zariadenie", "zhrn",
    }
    return bool(words & slovak_markers)


def friendly_error_message(error: Exception | str, user_message: str = "") -> str:
    text = str(error)
    lowered = text.lower()
    if "access to assets api was denied" in lowered or ("status_code" in lowered and "403" in lowered and "assets" in lowered):
        if _looks_slovak(user_message):
            return (
                "Jira token funguje, ale účet JiraBota nemá prístup k Jira Service Management a Assets. "
                "V Atlassian Administration mu najprv prideľ produktovú rolu Jira Service Management, potom ho v cieľovej Assets schéme "
                "pridaj ako Object Schema Manager. Následne požiadavku zopakuj."
            )
        return (
            "The Jira API token works, but the account used by the bot does not have access to the Jira Assets API. "
            "Add the required Assets permissions in Atlassian/Jira Service Management for the target schema, for example Object Schema User/Manager, "
            "or Assets administrator depending on whether the bot should only read or also assign devices."
        )
    if "jql" in lowered or "reserved word" in lowered or "vyhraden" in lowered:
        return (
            "I could not understand this as a Jira search, and I do not want to show you a technical error. "
            "Please phrase it more naturally, for example: \"list users\", "
            "\"show tickets\", or \"find open tickets about laptops\"."
        )
    if "no jira user found" in lowered or "pouzivatela" in lowered or "user found" in lowered:
        return "I could not find that user. Please try the full name or email."
    if "assets" in lowered:
        return "Something failed while reading or updating Assets. Please try a more precise device name or user."
    return "Something went wrong, but I will spare you the technical details. Please try again with a bit more detail."
