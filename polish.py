"""Rechtschreibkorrektur und Formatierung mit Claude Haiku 4.5.

Grundregel: ein Eintrag darf NIE verloren gehen. Wenn die API nicht erreichbar
ist, kein Key gesetzt ist oder sonst etwas schiefgeht, kommt der Rohtext
unveraendert zurueck - markiert, damit man es spaeter sieht.
"""
import logging

import anthropic

import prompts

log = logging.getLogger("lifelog.polish")

MODELL = "claude-haiku-4-5"
MAX_TOKENS = 600

SYSTEM = """You clean up a person's spoken-style diary entry so it reads well in their journal.

Rules:
- Fix spelling, typos, grammar and punctuation.
- Keep THEIR voice, their word choices and their level of detail. Do not make it
  sound formal or corporate.
- Output markdown bullet points, one thought per bullet. No heading, no preamble,
  no closing remark — only the bullets.
- Never invent anything. If they didn't mention it, it doesn't go in.
- Never drop anything. Every fact and feeling they mentioned must survive.
- If the entry is a single short thought, a single bullet is the right answer.

The entry is about {fokus}."""

# Wird beim ersten Aufruf erzeugt - nicht beim Import. Ohne API-Key wirft der
# Konstruktor, und das darf den Bot nicht am Starten hindern.
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()  # liest ANTHROPIC_API_KEY
    return _client


def _fallback(raw: str) -> str:
    """Rohtext als Stichpunkte, ohne KI. Markiert, damit man es nachbessern kann."""
    zeilen = [z.strip() for z in raw.splitlines() if z.strip()]
    punkte = "\n".join(f"- {z.lstrip('-*• ').strip()}" for z in zeilen)
    return f"{punkte}\n- ⚠️ *(unpolished — the cleanup step was unavailable)*"


async def polish(raw: str, slot: str) -> str:
    """Text aufbereiten. Gibt im Fehlerfall den Rohtext zurueck, wirft nie."""
    raw = raw.strip()
    if not raw:
        return ""

    try:
        resp = await _get_client().messages.create(
            model=MODELL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM.format(fokus=prompts.fokus(slot)),
            messages=[{"role": "user", "content": raw}],
        )
    except anthropic.RateLimitError:
        # Das SDK hat bereits zweimal mit Backoff wiederholt.
        log.warning("Claude: Rate-Limit, nutze Rohtext.")
        return _fallback(raw)
    except anthropic.APIStatusError as e:
        log.warning("Claude: HTTP %s, nutze Rohtext.", e.status_code)
        return _fallback(raw)
    except anthropic.APIConnectionError:
        log.warning("Claude: nicht erreichbar, nutze Rohtext.")
        return _fallback(raw)
    except Exception as e:  # fehlender Key, kaputte Config, alles Uebrige
        log.warning("Claude: %s: %s - nutze Rohtext.", type(e).__name__, e)
        return _fallback(raw)

    if resp.stop_reason == "refusal":
        log.warning("Claude hat abgelehnt, nutze Rohtext.")
        return _fallback(raw)

    text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        log.warning("Claude lieferte leeren Text, nutze Rohtext.")
        return _fallback(raw)

    if resp.stop_reason == "max_tokens":
        text += "\n- ⚠️ *(cut off — entry was longer than expected)*"
    return text


if __name__ == "__main__":
    # Handtest:  python polish.py
    import asyncio

    PROBE = "i wnet for a run this mornign, like 6km. then cofee and i red a bit. felt ok"
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(polish(PROBE, "morning")))
