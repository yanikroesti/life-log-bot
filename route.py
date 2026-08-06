"""Unaufgeforderte Nachrichten einordnen.

Wenn du dem Bot einfach so etwas schreibst - ohne dass gerade eine Frage offen
ist - entscheidet Claude Haiku, was gemeint ist:

  entry     ein Tagebuch-Eintrag  -> in welchen Abschnitt (morning/sleep/midday/evening)
  reminder  klingt nach Erinnerung -> Hinweis auf /erinnere (bewusst nicht automatisch,
            damit Termine und Tagebuch nicht durcheinandergeraten)
  other     Gruss, Frage, Test     -> kurze Hilfe

Ohne KI (kein Key / offline): nach Tageszeit einsortieren. Lieber ablegen als
verlieren - das ist die Grundhaltung des ganzen Bots.
"""
import json
import logging

import anthropic

log = logging.getLogger("lifelog.route")

MODELL = "claude-haiku-4-5"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
              "Freitag", "Samstag", "Sonntag"]

SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["entry", "reminder", "other"],
            "description": "entry = a diary/log note about the day; "
                           "reminder = they want to be reminded of a future task; "
                           "other = greeting, question, test, small talk",
        },
        "slot": {
            "type": "string",
            "enum": ["morning", "sleep", "midday", "evening"],
            "description": "only meaningful when kind is 'entry'; "
                           "otherwise pick the closest by time of day",
        },
    },
    "required": ["kind", "slot"],
    "additionalProperties": False,
}

SYSTEM = """You sort a person's unprompted Telegram message into one of three kinds.

Right now it is {jetzt} ({wochentag}) in their timezone.

Kinds:
- "entry": a note about their day — what they did, how they slept, how they feel,
  what they got done, plans. This is the common case; when in doubt, choose entry.
- "reminder": they want to be reminded of a FUTURE task at a specific time
  ("erinnere mich...", "morgen um 9 Arzt", "nicht vergessen: ..."). Only when it is
  clearly about a future action to be reminded of.
- "other": a greeting, a question to the bot, a command they mistyped, a test.

For "entry", pick the section:
- "morning": the morning routine, what they did after waking.
- "sleep": how they slept — hours, quality, how rested.
- "midday": current mood/energy and the plan for the rest of the day.
- "evening": what they finished/achieved, how they feel now, plans for tomorrow.
Let the CONTENT lead ("slept badly" -> sleep even at noon), and use the time of
day only as a tie-breaker."""


def slot_by_time(local_dt) -> str:
    """Grober Standard-Slot nach Uhrzeit - fuer den Fall ohne KI."""
    h = local_dt.hour
    if 4 <= h < 11:
        return "morning"
    if 11 <= h < 15:
        return "midday"
    return "evening"


_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


async def route(text: str, jetzt) -> dict:
    """Nachricht einordnen. Gibt {'kind','slot','fallback'} zurueck, wirft nie.

    fallback=True heisst: die KI war nicht erreichbar, es wurde nach Uhrzeit
    entschieden (immer als 'entry').
    """
    text = text.strip()
    default = {"kind": "entry", "slot": slot_by_time(jetzt), "fallback": True}
    if not text:
        return default

    try:
        resp = await _get_client().messages.create(
            model=MODELL,
            max_tokens=60,
            system=SYSTEM.format(
                jetzt=jetzt.strftime("%Y-%m-%d %H:%M"),
                wochentag=WOCHENTAGE[jetzt.weekday()],
            ),
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": text}],
        )
    except (anthropic.APIConnectionError, anthropic.RateLimitError,
            anthropic.APIStatusError) as e:
        log.warning("Routing: %s - sortiere nach Uhrzeit.", type(e).__name__)
        return default
    except Exception as e:
        log.warning("Routing: %s: %s - sortiere nach Uhrzeit.", type(e).__name__, e)
        return default

    if resp.stop_reason == "refusal":
        return default

    rohtext = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = json.loads(rohtext)
    except json.JSONDecodeError:
        return default

    kind = d.get("kind")
    slot = d.get("slot")
    if kind not in ("entry", "reminder", "other"):
        return default
    if kind == "entry" and slot not in ("morning", "sleep", "midday", "evening"):
        slot = slot_by_time(jetzt)
    return {"kind": kind, "slot": slot, "fallback": False}
