"""Die vier Slots: was gefragt wird und wie die Antwort aufbereitet wird.

Die Fragen sind auf Englisch, passend zum Stil der bestehenden Daily Notes
("What I Did", "Open Items", "Today's Plan").
"""

# Reihenfolge = Reihenfolge im Tages-File.
SLOTS: dict[str, dict] = {
    "morning": {
        "frage": (
            "☀️ Good morning. What did your morning look like so far?\n"
            "Just type it out — spelling doesn't matter, I'll clean it up."
        ),
        "ueberschrift": "## Morning Routine",
        "fokus": "the morning routine: what they did, in what order, how it went",
    },
    "sleep": {
        "frage": (
            "😴 And how did you sleep?\n"
            "Roughly how many hours, how good it was, how you feel now."
        ),
        "ueberschrift": "## Sleep",
        "fokus": "sleep: duration, quality, and how rested they feel",
    },
    "midday": {
        "frage": (
            "🕛 Lunch check-in. How are you feeling right now, "
            "and what's the plan for the rest of the day?"
        ),
        "ueberschrift": "## Midday",
        "fokus": "their current mood/energy and their plan for the rest of the day",
    },
    "evening": {
        "frage": (
            "🌙 Evening review.\n"
            "What did you get done? What did you achieve? "
            "How are you feeling? And what's the plan for tomorrow?"
        ),
        "ueberschrift": "## Evening",
        "fokus": (
            "what they completed, what they achieved, how they feel, "
            "and their plan for tomorrow"
        ),
    },
}

# Nach diesem Slot wird sofort der naechste nachgeschoben (gleiches Gespraech).
NAECHSTER_SLOT = {"morning": "sleep"}


def frage(slot: str) -> str:
    return SLOTS[slot]["frage"]


def ueberschrift(slot: str) -> str:
    return SLOTS[slot]["ueberschrift"]


def fokus(slot: str) -> str:
    return SLOTS[slot]["fokus"]
