"""Erinnerungen aus normaler Sprache verstehen.

Zwei Wege, in dieser Reihenfolge:

1. Feste Formate per Regex - kostet nichts, braucht kein Internet.
     2026-07-25 09:00 Arzt anrufen
     taeglich 20:00 lernen
     montags 18:00 Muell rausstellen

2. Alles andere geht an Claude Haiku 4.5 mit einem festen JSON-Schema
   ("structured outputs"), damit die Antwort garantiert die richtige Form hat.
     morgen um 9 den Arzt anrufen
     jeden zweiten Tag ...      -> wird abgelehnt, das kann das Schema nicht

Was die KI zurueckgibt, wird in Python nochmal geprueft. Ein Modell, das ein
Datum wie "2026-13-45" halluziniert, darf nicht bis in die Datenbank kommen.
"""
import json
import logging
import re
from datetime import datetime, timedelta

import anthropic

log = logging.getLogger("lifelog.reminders")

MODELL = "claude-haiku-4-5"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
              "Freitag", "Samstag", "Sonntag"]

_WT_INDEX = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonnabend": 5, "sonntag": 6,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "verstanden": {
            "type": "boolean",
            "description": "false if this is not a reminder or the time is unclear",
        },
        "art": {"type": "string", "enum": ["once", "daily", "weekly"]},
        "datum": {"type": "string", "description": "YYYY-MM-DD for 'once', else empty string"},
        "zeit": {"type": "string", "description": "HH:MM in 24h format"},
        "wochentag": {
            "type": "integer",
            "description": "for 'weekly': 0=Monday .. 6=Sunday. Otherwise -1.",
        },
        "text": {
            "type": "string",
            "description": "what to remind about, short, without the time information",
        },
    },
    "required": ["verstanden", "art", "datum", "zeit", "wochentag", "text"],
    "additionalProperties": False,
}

SYSTEM = """You turn a German reminder request into structured data.

Right now it is {jetzt} ({wochentag}) in the user's timezone.
Resolve relative expressions ("morgen", "übermorgen", "nächsten Freitag",
"in 2 Stunden") against that exact moment.

- "art": "once" for a single point in time, "daily" for every day,
  "weekly" for a fixed weekday every week.
- "datum" only for "once", format YYYY-MM-DD. Empty string otherwise.
- "zeit" always, 24h HH:MM. If no time is given, use 09:00 for dates and
  keep the user's wording in mind (e.g. "abends" -> 20:00, "morgens" -> 08:00).
- "wochentag" only for "weekly" (0=Monday .. 6=Sunday), otherwise -1.
- "text" is what should be remembered, in German, short, no time words.
- Set "verstanden" to false if this isn't a reminder, or if you cannot work out
  a concrete time. Never guess a date you are unsure about."""

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


class Unklar(Exception):
    """Konnte nicht in eine Erinnerung uebersetzt werden."""


# ---------- Pruefung ----------

def _pruefe(d: dict) -> dict:
    """Rohes Ergebnis (Regex oder KI) validieren. Wirft Unklar."""
    art = d.get("art")
    if art not in ("once", "daily", "weekly"):
        raise Unklar("unbekannte Art")

    zeit = (d.get("zeit") or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", zeit):
        raise Unklar("keine gueltige Uhrzeit")
    h, m = (int(x) for x in zeit.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise Unklar("Uhrzeit ausserhalb des Bereichs")
    zeit = f"{h:02d}:{m:02d}"

    text = (d.get("text") or "").strip()
    if not text:
        raise Unklar("kein Text")

    if art == "once":
        datum = (d.get("datum") or "").strip()
        try:
            wann = datetime.strptime(f"{datum} {zeit}", "%Y-%m-%d %H:%M")
        except ValueError:
            raise Unklar("kein gueltiges Datum")
        return {"art": "once", "wann": wann.strftime("%Y-%m-%d %H:%M"),
                "zeit": zeit, "wochentag": -1, "text": text}

    if art == "weekly":
        wt = d.get("wochentag", -1)
        if not isinstance(wt, int) or not (0 <= wt <= 6):
            raise Unklar("kein gueltiger Wochentag")
        return {"art": "weekly", "wann": "", "zeit": zeit, "wochentag": wt, "text": text}

    return {"art": "daily", "wann": "", "zeit": zeit, "wochentag": -1, "text": text}


# ---------- Weg 1: feste Formate ----------

def _parse_explizit(eingabe: str) -> dict | None:
    s = eingabe.strip()

    # 2026-07-25 09:00 Arzt anrufen
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$", s, re.S)
    if m:
        return _pruefe({"art": "once", "datum": m[1], "zeit": m[2], "text": m[3]})

    # taeglich 20:00 lernen   (mit und ohne Umlaut, "ae" wie auf CH-Tastatur getippt)
    m = re.match(r"^(?:t(?:ä|ae|a)glich|jeden\s+tag)\s+(\d{1,2}:\d{2})\s+(.+)$", s, re.I | re.S)
    if m:
        return _pruefe({"art": "daily", "zeit": m[1], "text": m[2], "datum": "", "wochentag": -1})

    # montags 18:00 Muell  /  jeden montag 18:00 Muell
    m = re.match(
        r"^(?:jeden\s+)?(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)s?"
        r"\s+(\d{1,2}:\d{2})\s+(.+)$",
        s, re.I | re.S,
    )
    if m:
        return _pruefe({"art": "weekly", "zeit": m[2], "text": m[3], "datum": "",
                        "wochentag": _WT_INDEX[m[1].lower()]})

    return None


# ---------- Weg 2: Claude ----------

async def _parse_ki(eingabe: str, jetzt: datetime) -> dict:
    try:
        resp = await _get_client().messages.create(
            model=MODELL,
            max_tokens=300,
            system=SYSTEM.format(
                jetzt=jetzt.strftime("%Y-%m-%d %H:%M"),
                wochentag=WOCHENTAGE[jetzt.weekday()],
            ),
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": eingabe}],
        )
    except anthropic.APIConnectionError:
        raise Unklar("Claude ist gerade nicht erreichbar")
    except anthropic.RateLimitError:
        raise Unklar("Claude ist ausgelastet")
    except anthropic.APIStatusError as e:
        raise Unklar(f"Claude antwortet mit HTTP {e.status_code}")
    except Exception as e:
        log.warning("Claude-Parsing: %s: %s", type(e).__name__, e)
        raise Unklar("die Zeiterkennung ist gerade nicht verfuegbar")

    if resp.stop_reason == "refusal":
        raise Unklar("Claude hat die Anfrage abgelehnt")

    rohtext = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = json.loads(rohtext)
    except json.JSONDecodeError:
        raise Unklar("unverstaendliche Antwort der Zeiterkennung")

    if not d.get("verstanden"):
        raise Unklar("ich konnte daraus keinen konkreten Zeitpunkt lesen")
    return _pruefe(d)


# ---------- Oeffentlich ----------

async def parse(eingabe: str, jetzt: datetime) -> dict:
    """Eingabe -> {'art','wann','zeit','wochentag','text'}. Wirft Unklar."""
    eingabe = eingabe.strip()
    if not eingabe:
        raise Unklar("leere Eingabe")

    explizit = _parse_explizit(eingabe)
    if explizit:
        return explizit
    return await _parse_ki(eingabe, jetzt)


# ---------- Zeitvorschlaege, wenn keine Zeit dabeisteht ----------

VORSCHLAG_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "what to remind about, short, German, without time words",
        },
        "vorschlaege": {
            "type": "array",
            "description": "exactly 4 suggested moments, earliest first",
            "items": {
                "type": "object",
                "properties": {
                    "datum": {"type": "string", "description": "YYYY-MM-DD"},
                    "zeit": {"type": "string", "description": "HH:MM, 24h"},
                    "grund": {
                        "type": "string",
                        "description": "very short German label, max 3 words, "
                                       "e.g. 'gleich', 'nach der Arbeit', 'Praxiszeit'",
                    },
                },
                "required": ["datum", "zeit", "grund"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["text", "vorschlaege"],
    "additionalProperties": False,
}

VORSCHLAG_SYSTEM = """The user wants to be reminded of something but gave no time.
Suggest exactly 4 moments that genuinely fit THIS task.

Right now it is {jetzt} ({wochentag}) in their timezone.

Rules:
- Every suggestion must be in the future. Prefer today; once today is nearly over,
  move to tomorrow.
- Fit the task, don't just list round hours. A doctor's office is reachable during
  office hours; taking out the bin belongs in the evening; a workout fits before
  work or after; calling a friend fits the evening.
- Spread them out so there is a real choice — not 4 times within one hour.
- "grund" is a very short German label shown on a button (max 3 words).
- "text" is what to remember, in German, short, without any time words.

The user is a Swiss electrician apprentice; on weekdays he is at work or at
vocational school during the day."""


def _standard_vorschlaege(jetzt: datetime) -> list[dict]:
    """Ohne KI: generische, aber brauchbare Zeitpunkte in der Zukunft."""
    # "in einer Stunde" auf die naechste Viertelstunde runden - 20:58 sieht
    # auf einem Knopf einfach schlechter aus als 21:00.
    gleich = (jetzt + timedelta(hours=1)).replace(second=0, microsecond=0)
    gleich += timedelta(minutes=(-gleich.minute) % 15)

    kandidaten = [
        (gleich, "in einer Stunde"),
        (jetzt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=3), "spaeter"),
        (jetzt.replace(hour=18, minute=0, second=0, microsecond=0), "am Abend"),
        (jetzt.replace(hour=20, minute=0, second=0, microsecond=0), "spaeter Abend"),
        ((jetzt + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0),
         "morgen frueh"),
        ((jetzt + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0),
         "morgen mittag"),
        ((jetzt + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0),
         "morgen Abend"),
        ((jetzt + timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0),
         "morgen spaet"),
    ]
    raus = []
    for wann, grund in sorted(kandidaten, key=lambda k: k[0]):
        if wann <= jetzt:
            continue
        if 0 <= wann.hour < 7:
            continue  # mitten in der Nacht will niemand geweckt werden
        raus.append({"datum": wann.strftime("%Y-%m-%d"),
                     "zeit": wann.strftime("%H:%M"), "grund": grund})
        if len(raus) == 4:
            break
    return raus


def _saubere_vorschlaege(rohe: list, jetzt: datetime) -> list[dict]:
    """Vergangenes und Doppeltes raus, chronologisch sortieren, auf 4 begrenzen."""
    gesehen, gut = set(), []
    for v in rohe or []:
        if not isinstance(v, dict):
            continue
        datum, zeit = (v.get("datum") or "").strip(), (v.get("zeit") or "").strip()
        try:
            wann = datetime.strptime(f"{datum} {zeit}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if jetzt.tzinfo:
            wann = wann.replace(tzinfo=jetzt.tzinfo)
        if wann <= jetzt:
            continue  # das Modell hat in die Vergangenheit geraten
        schluessel = f"{datum} {zeit}"
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        grund = (v.get("grund") or "").strip()[:24]
        gut.append({"datum": datum, "zeit": zeit, "grund": grund, "_wann": wann})

    gut.sort(key=lambda v: v["_wann"])
    for v in gut:
        v.pop("_wann")
    return gut[:4]


async def vorschlaege(eingabe: str, jetzt: datetime) -> dict:
    """-> {'text', 'vorschlaege': [{datum, zeit, grund}, ...]}. Wirft nie."""
    eingabe = eingabe.strip()
    notfall = {"text": eingabe[:80], "vorschlaege": _standard_vorschlaege(jetzt)}

    try:
        resp = await _get_client().messages.create(
            model=MODELL,
            max_tokens=400,
            system=VORSCHLAG_SYSTEM.format(
                jetzt=jetzt.strftime("%Y-%m-%d %H:%M"),
                wochentag=WOCHENTAGE[jetzt.weekday()],
            ),
            output_config={"format": {"type": "json_schema", "schema": VORSCHLAG_SCHEMA}},
            messages=[{"role": "user", "content": eingabe}],
        )
    except Exception as e:
        log.warning("Vorschlaege: %s: %s - nutze Standardzeiten.", type(e).__name__, e)
        return notfall

    if resp.stop_reason == "refusal":
        return notfall

    rohtext = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = json.loads(rohtext)
    except json.JSONDecodeError:
        return notfall

    liste = _saubere_vorschlaege(d.get("vorschlaege"), jetzt)
    if len(liste) < 2:
        # Zu wenig Brauchbares uebrig - lieber generische Zeiten als eine Sackgasse.
        liste = _standard_vorschlaege(jetzt)
    text = (d.get("text") or "").strip() or eingabe[:80]
    return {"text": text, "vorschlaege": liste}


def beschreibe_zeitpunkt(datum: str, zeit: str, jetzt: datetime) -> str:
    """'2026-07-25 09:00' -> 'morgen um 09:00' / 'Sa, 25.07. um 09:00'."""
    try:
        wann = datetime.strptime(f"{datum} {zeit}", "%Y-%m-%d %H:%M")
    except ValueError:
        return f"{datum} {zeit}"
    tage = (wann.date() - jetzt.date()).days
    if tage == 0:
        return f"heute um {zeit}"
    if tage == 1:
        return f"morgen um {zeit}"
    return f"{WOCHENTAGE[wann.weekday()][:2]}, {wann:%d.%m.} um {zeit}"


def beschreibe(r: dict) -> str:
    """Lesbare Zusammenfassung fuer die Bestaetigung und die Liste."""
    if r["art"] == "once":
        wann = datetime.strptime(r["wann"], "%Y-%m-%d %H:%M")
        return f"{WOCHENTAGE[wann.weekday()]}, {wann:%d.%m.%Y} um {wann:%H:%M}"
    if r["art"] == "weekly":
        return f"jeden {WOCHENTAGE[r['wochentag']]} um {r['zeit']}"
    return f"jeden Tag um {r['zeit']}"


if __name__ == "__main__":
    # Handtest der Regex-Wege (ohne API):  python reminders.py
    logging.basicConfig(level=logging.INFO)
    for probe in [
        "2026-07-25 09:00 Arzt anrufen",
        "taeglich 20:00 lernen",
        "täglich 20:00 lernen",
        "jeden Tag 06:30 Kaffee",
        "montags 18:00 Muell rausstellen",
        "jeden Freitag 16:00 Werkzeug zurueckgeben",
        "2026-13-45 09:00 unmoegliches Datum",
        "taeglich 99:99 unmoegliche Zeit",
        "morgen um 9 den Arzt anrufen",
    ]:
        try:
            r = _parse_explizit(probe)
        except Unklar as e:
            print(f"{probe!r:44} -> abgelehnt: {e}")
            continue
        if r is None:
            print(f"{probe!r:44} -> geht an Claude")
        else:
            print(f"{probe!r:44} -> {beschreibe(r)} | {r['text']}")
