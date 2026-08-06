"""Life Log - Telegram-Bot fuers taegliche Selbstprotokoll + Erinnerungen.

Start:  python bot.py
Token:  Umgebungsvariable LIFELOG_TOKEN / BOT_TOKEN  oder  token.txt im Ordner.
KI-Key: Umgebungsvariable ANTHROPIC_API_KEY (ohne den laeuft der Bot trotzdem,
        die Eintraege sind dann nur nicht korrigiert).

Engine-Muster uebernommen vom Stromtraining-Bot: run_daily mit Zeitzone pro
Benutzer, expliziter Startablauf (Python 3.12+/3.14), Retry beim Verbinden.
"""
import asyncio
import logging
import os
from datetime import datetime, time as dtime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    HAS_ZONEINFO = True
except Exception:  # Fallback falls Zeitzonen-Daten fehlen
    HAS_ZONEINFO = False

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import polish
import prompts
import reminders
import route
import storage
import vault

STANDARD_TZ = "Europe/Zurich"

ZONE_ALIASES = {
    "zurich": "Europe/Zurich",
    "zürich": "Europe/Zurich",
    "ch": "Europe/Zurich",
    "schweiz": "Europe/Zurich",
    "utc": "UTC",
    "gmt": "UTC",
}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s - %(message)s", level=logging.INFO
)
# httpx loggt die komplette Request-URL inkl. Token -> drosseln, damit der
# Bot-Token niemals in Konsole oder journal landet.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("lifelog")


# ---------- Zeitzonen ----------

def resolve_zone(name: str):
    """Eingabe (Kurzname oder IANA) -> gueltiger IANA-Name oder None."""
    if not HAS_ZONEINFO:
        return None
    key = name.strip().lower()
    iana = ZONE_ALIASES.get(key, name.strip())
    try:
        ZoneInfo(iana)
        return iana
    except Exception:
        return None


def tz_for(name: str):
    if not HAS_ZONEINFO:
        return None
    try:
        return ZoneInfo(name or STANDARD_TZ)
    except Exception:
        return ZoneInfo(STANDARD_TZ)


def tz_of(chat_id: int):
    user = storage.get_user(chat_id) or {}
    return tz_for(user.get("tz") or STANDARD_TZ)


def heute_fuer(chat_id: int) -> str:
    return vault.heute(tz_of(chat_id))


# ---------- Zeitplan: taegliche Fragen ----------

def schedule_user(application: Application, chat_id: int):
    """Drei taegliche Jobs setzen (sleep haengt an morning, hat keinen Timer)."""
    jq = application.job_queue
    user = storage.get_user(chat_id)

    for slot in storage.GEPLANTE_SLOTS:
        for job in jq.get_jobs_by_name(f"{slot}_{chat_id}"):
            job.schedule_removal()

    if not user or not user["aktiv"]:
        return

    tz = tz_for(user.get("tz") or STANDARD_TZ)
    for slot in storage.GEPLANTE_SLOTS:
        h, m = (int(x) for x in storage.zeit_fuer(user, slot).split(":"))
        jq.run_daily(
            slot_job,
            time=dtime(h, m, tzinfo=tz) if tz else dtime(h, m),
            chat_id=chat_id,
            name=f"{slot}_{chat_id}",
            data=slot,
        )


async def slot_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    user = storage.get_user(chat_id)
    if not user or not user["aktiv"]:
        return
    await frage_stellen(context.bot, chat_id, context.job.data)


async def frage_stellen(bot, chat_id: int, slot: str):
    storage.set_pending(chat_id, slot, heute_fuer(chat_id))
    await bot.send_message(chat_id, prompts.frage(slot))


# ---------- Zeitplan: Erinnerungen ----------

def _ptb_wochentag(py_wochentag: int) -> int:
    """Python zaehlt 0=Montag, python-telegram-bot 0=Sonntag."""
    return (py_wochentag + 1) % 7


def schedule_reminder(application: Application, r: dict) -> bool:
    """Erinnerung einplanen. False = einmaliger Termin liegt in der Vergangenheit."""
    jq = application.job_queue
    for job in jq.get_jobs_by_name(f"rem_{r['id']}"):
        job.schedule_removal()

    tz = tz_of(r["chat_id"])
    h, m = (int(x) for x in r["zeit"].split(":"))

    if r["art"] == "once":
        wann = datetime.strptime(r["wann"], "%Y-%m-%d %H:%M")
        if tz:
            wann = wann.replace(tzinfo=tz)
        if wann <= datetime.now(tz):
            return False
        jq.run_once(reminder_job, when=wann, chat_id=r["chat_id"],
                    name=f"rem_{r['id']}", data=r["id"])
        return True

    tage = tuple(range(7)) if r["art"] == "daily" else (_ptb_wochentag(r["wochentag"]),)
    jq.run_daily(
        reminder_job,
        time=dtime(h, m, tzinfo=tz) if tz else dtime(h, m),
        days=tage,
        chat_id=r["chat_id"],
        name=f"rem_{r['id']}",
        data=r["id"],
    )
    return True


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    r = storage.get_reminder(context.job.data)
    if not r or not r["aktiv"]:
        return
    await context.bot.send_message(r["chat_id"], f"⏰ {r['text']}")
    if r["art"] == "once":
        storage.deactivate_reminder(r["id"])


# ---------- Antworten ----------

def _label(slot: str) -> str:
    """'## Morning Routine' -> 'Morning Routine' fuer Bestaetigungen."""
    return prompts.ueberschrift(slot).lstrip("# ").strip()


async def _ablegen(context, chat_id: int, datum: str, slot: str, roh: str) -> bool:
    """Aufbereiten, in DB + Vault schreiben. False = Vault-Fehler (schon gemeldet).

    Nimmt bewusst kein `update`: wird auch aus Button-Antworten heraus benutzt,
    wo es keine Nachricht zum Antworten gibt.
    """
    await context.bot.send_chat_action(chat_id, "typing")
    schoen = await polish.polish(roh, slot)
    storage.save_entry(chat_id, datum, slot, roh, schoen)
    try:
        vault.append(slot, schoen, datum=datum)
    except OSError as e:
        log.error("Vault-Schreiben fehlgeschlagen (%s %s): %s", datum, slot, e)
        await context.bot.send_message(
            chat_id,
            "⚠️ Gespeichert, aber das Schreiben in den Vault hat nicht geklappt "
            f"({e.__class__.__name__}). Der Text ist in der Datenbank sicher — "
            "mit /heute siehst du ihn."
        )
        return False
    return True


def _erinnerung_anlegen(application, chat_id: int, d: dict) -> int | None:
    """Erinnerung speichern und einplanen. None = Zeitpunkt liegt in der Vergangenheit."""
    rid = storage.add_reminder(
        chat_id, d["text"], d["art"], d.get("wann", ""), d["zeit"], d.get("wochentag", -1)
    )
    if not schedule_reminder(application, storage.get_reminder(rid)):
        storage.deactivate_reminder(rid)
        return None
    return rid


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    roh = update.message.text.strip()
    if not roh:
        return

    slot, datum = storage.get_pending(chat_id)
    if slot:
        await _antwort_auf_frage(update, context, chat_id, slot,
                                 datum or heute_fuer(chat_id), roh)
        return

    # Warte ich auf eine Uhrzeit fuer eine Erinnerung? Dann zuerst das versuchen.
    offen = storage.latest_pending_reminder(chat_id)
    if offen and await _zeit_nachgereicht(update, context, chat_id, offen, roh):
        return

    await _spontane_nachricht(update, context, chat_id, roh)


async def _zeit_nachgereicht(update, context, chat_id, offen, roh) -> bool:
    """Getippte Uhrzeit zu einer offenen Erinnerung. False = war keine Zeit."""
    await context.bot.send_chat_action(chat_id, "typing")
    jetzt = datetime.now(tz_of(chat_id))
    try:
        # Uhrzeit und Anliegen zusammensetzen: "um 17:30" + "den Arzt anrufen"
        d = await reminders.parse(f"{roh} {offen['text']}", jetzt)
    except reminders.Unklar:
        # Keine Zeit -> die Zeitfrage fallenlassen und normal weiterbehandeln.
        storage.delete_pending_reminder(offen["id"])
        return False

    storage.delete_pending_reminder(offen["id"])
    rid = _erinnerung_anlegen(context.application, chat_id, d)
    if rid is None:
        await update.message.reply_text(
            f"Das liegt schon in der Vergangenheit ({reminders.beschreibe(d)}). "
            "Nichts angelegt."
        )
        return True

    await update.message.reply_text(
        f"⏰ Merke ich mir: {reminders.beschreibe(d)}\n"
        f"„{d['text']}“\n\n"
        f"Doch nicht? /loeschen {rid}"
    )
    return True


async def _antwort_auf_frage(update, context, chat_id, slot, datum, roh):
    """Antwort auf eine offene Frage - kann die Schlaf-Frage nachziehen."""
    # Erst die offene Frage schliessen: wenn unten etwas schiefgeht, haengt der
    # Bot nicht in einem Zustand fest, in dem jede weitere Nachricht denselben
    # Slot ueberschreibt.
    storage.set_pending(chat_id, None, None)

    if not await _ablegen(context, chat_id, datum, slot, roh):
        return

    folge = prompts.NAECHSTER_SLOT.get(slot)
    if folge:
        await update.message.reply_text("Got it. ✍️")
        storage.set_pending(chat_id, folge, datum)
        await context.bot.send_message(chat_id, prompts.frage(folge))
    else:
        await update.message.reply_text(f"Saved to {datum}. ✍️")


async def _erinnerung_ohne_command(update, context, chat_id, roh):
    """Nachricht klingt nach Erinnerung - ohne dass /erinnere davorstand."""
    jetzt = datetime.now(tz_of(chat_id))

    # Steht eine Zeit drin? Dann direkt anlegen, kein Nachfragen.
    try:
        d = await reminders.parse(roh, jetzt)
    except reminders.Unklar:
        d = None

    if d:
        rid = _erinnerung_anlegen(context.application, chat_id, d)
        if rid is None:
            await update.message.reply_text(
                f"Das liegt schon in der Vergangenheit ({reminders.beschreibe(d)}). "
                "Nichts angelegt."
            )
            return
        await update.message.reply_text(
            f"⏰ Merke ich mir: {reminders.beschreibe(d)}\n"
            f"„{d['text']}“\n\n"
            f"Doch nicht? /loeschen {rid}"
        )
        return

    # Keine Zeit dabei -> vier passende Zeitpunkte vorschlagen.
    v = await reminders.vorschlaege(roh, jetzt)
    pid = storage.add_pending_reminder(chat_id, v["text"], roh)

    reihen, paar = [], []
    for s in v["vorschlaege"]:
        wann = reminders.beschreibe_zeitpunkt(s["datum"], s["zeit"], jetzt)
        # "heute um 18:00" -> "18:00", sonst Tag mitnehmen
        kurz = s["zeit"] if wann.startswith("heute") else wann.replace(" um ", " ")
        label = f"{kurz} · {s['grund']}" if s["grund"] else kurz
        paar.append(InlineKeyboardButton(
            label[:40], callback_data=f"rt|{pid}|{s['datum']}|{s['zeit']}"
        ))
        if len(paar) == 2:
            reihen.append(paar)
            paar = []
    if paar:
        reihen.append(paar)
    reihen.append([InlineKeyboardButton(
        "📓 Kein Termin — ins Tagebuch", callback_data=f"rd|{pid}"
    )])

    await update.message.reply_text(
        f"⏰ Wann soll ich dich erinnern?\n„{v['text']}“\n\n"
        "Tippe eine Zeit an — oder schreib mir einfach eine "
        "(z. B. „um 17:30“ oder „morgen um 9“).",
        reply_markup=InlineKeyboardMarkup(reihen),
    )


async def _spontane_nachricht(update, context, chat_id, roh):
    """Nachricht ohne offene Frage: selbst einordnen und ablegen."""
    await context.bot.send_chat_action(chat_id, "typing")
    entscheidung = await route.route(roh, datetime.now(tz_of(chat_id)))

    if entscheidung["kind"] == "reminder":
        await _erinnerung_ohne_command(update, context, chat_id, roh)
        return

    if entscheidung["kind"] == "other":
        await update.message.reply_text(
            "Schreib mir einfach, wie dein Tag laeuft — ich sortiere es in deine "
            "Notiz ein (Morgen / Schlaf / Mittag / Abend).\n\n"
            "/erinnere … – Erinnerung · /heute – heutige Eintraege · /status"
        )
        return

    slot = entscheidung["slot"]
    datum = heute_fuer(chat_id)
    if not await _ablegen(context, chat_id, datum, slot, roh):
        return

    hinweis = "\n(Zeiterkennung war offline — nach Uhrzeit einsortiert.)" \
        if entscheidung.get("fallback") else ""
    await update.message.reply_text(
        f"✍️ In deine Notiz unter *{_label(slot)}* gelegt.{hinweis}\n"
        f"Falsch einsortiert? /nachtrag <slot>",
        parse_mode="Markdown",
    )


# ---------- Knopfdruck bei den Zeitvorschlaegen ----------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()  # Ladekringel im Telegram-Client beenden
    chat_id = q.message.chat_id
    teile = (q.data or "").split("|")

    pid = int(teile[1]) if len(teile) > 1 and teile[1].isdigit() else 0
    p = storage.get_pending_reminder(pid)
    # Besitz pruefen - sonst koennte ein fremder Chat an den Eintrag.
    if not p or p["chat_id"] != chat_id:
        await q.edit_message_text("Das ist nicht mehr aktuell.")
        return

    # "Doch kein Termin" -> als Tagebuch-Eintrag ablegen
    if teile[0] == "rd":
        storage.delete_pending_reminder(pid)
        jetzt = datetime.now(tz_of(chat_id))
        slot = route.slot_by_time(jetzt)
        await q.edit_message_text("Alles klar, kein Termin.")
        if await _ablegen(context, chat_id, heute_fuer(chat_id), slot, p["roh"]):
            await context.bot.send_message(
                chat_id, f"✍️ Stattdessen unter *{_label(slot)}* abgelegt.",
                parse_mode="Markdown",
            )
        return

    if teile[0] != "rt" or len(teile) != 4:
        await q.edit_message_text("Das habe ich nicht verstanden.")
        return

    datum, zeit = teile[2], teile[3]
    storage.delete_pending_reminder(pid)
    d = {"art": "once", "wann": f"{datum} {zeit}", "zeit": zeit,
         "wochentag": -1, "text": p["text"]}

    rid = _erinnerung_anlegen(context.application, chat_id, d)
    if rid is None:
        await q.edit_message_text(
            "Der Zeitpunkt ist inzwischen vorbei. Schreib mir einfach eine neue Zeit."
        )
        return

    jetzt = datetime.now(tz_of(chat_id))
    await q.edit_message_text(
        f"⏰ {reminders.beschreibe_zeitpunkt(datum, zeit, jetzt)}\n"
        f"„{p['text']}“\n\n"
        f"Doch nicht? /loeschen {rid}"
    )


# ---------- Befehle: Protokoll ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    storage.set_aktiv(chat_id, True)
    schedule_user(context.application, chat_id)
    user = storage.get_user(chat_id)
    await update.message.reply_text(
        "📓 Life Log laeuft.\n\n"
        "Ich melde mich dreimal am Tag. Du antwortest einfach normal — "
        "Tippfehler sind egal, ich raeume auf und lege es in deiner Daily Note ab.\n\n"
        "Du kannst mir aber auch jederzeit von dir aus schreiben — ich sortiere es "
        "selbst in den passenden Abschnitt ein (Morgen / Schlaf / Mittag / Abend).\n\n"
        f"Morgens  {user['t_morning']}  (danach frage ich noch nach dem Schlaf)\n"
        f"Mittags  {user['t_midday']}\n"
        f"Abends   {user['t_evening']}\n"
        f"Zone     {user['tz']}\n\n"
        "⏰ Erinnerungen brauchen keinen Befehl. Schreib einfach:\n"
        "„morgen um 9 den Arzt anrufen“ — lege ich direkt an\n"
        "„ich muss den Arzt anrufen“ — ich schlage dir vier Zeiten vor\n"
        "/erinnerungen · /loeschen 3\n\n"
        "Weiteres:\n"
        "/zeit morning 06:45 · /zone utc\n"
        "/heute · /nachtrag evening · /status · /stop"
    )


async def cmd_zeit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    try:
        slot = context.args[0].lower()
        if slot not in storage.GEPLANTE_SLOTS:
            raise ValueError
        h, m = (int(x) for x in context.args[1].split(":"))
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Nutze: /zeit <morning|midday|evening> HH:MM\n"
            "z. B.  /zeit morning 06:45\n"
            "(sleep hat keine eigene Zeit — die Frage kommt direkt nach morning)"
        )
        return

    storage.set_zeit(chat_id, slot, f"{h:02d}:{m:02d}")
    schedule_user(context.application, chat_id)
    zone = (storage.get_user(chat_id).get("tz")) or STANDARD_TZ
    await update.message.reply_text(f"{slot} kommt jetzt um {h:02d}:{m:02d} ({zone}).")


async def cmd_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)

    if not context.args:
        zone = (storage.get_user(chat_id).get("tz")) or STANDARD_TZ
        await update.message.reply_text(
            f"Aktuelle Zeitzone: {zone}\n"
            "Aendern z. B.:  /zone zurich  ·  /zone utc  ·  /zone Europe/Berlin"
        )
        return

    iana = resolve_zone(context.args[0])
    if not iana:
        await update.message.reply_text(
            "Unbekannte Zone. Versuch:  /zone zurich  ·  /zone utc  ·  "
            "oder eine IANA-Zone wie Europe/Berlin."
        )
        return

    storage.set_tz(chat_id, iana)
    schedule_user(context.application, chat_id)
    # Erinnerungen haengen an derselben Zone -> neu einplanen.
    for r in storage.reminders_for(chat_id):
        if not schedule_reminder(context.application, r):
            storage.deactivate_reminder(r["id"])

    z = tz_for(iana)
    jetzt = f" (dort ist es jetzt {datetime.now(z):%H:%M})" if z else ""
    await update.message.reply_text(f"Zeitzone gesetzt: {iana}{jetzt}.")


async def cmd_heute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    datum = heute_fuer(chat_id)
    eintraege = storage.entries_for_day(chat_id, datum)
    if not eintraege:
        await update.message.reply_text(f"Fuer {datum} ist noch nichts da.")
        return
    teile = [f"📓 {datum}"]
    for e in eintraege:
        teile.append(f"\n{prompts.ueberschrift(e['slot'])}\n{e['polished']}")
    await update.message.reply_text("\n".join(teile))


async def cmd_nachtrag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    slot = context.args[0].lower() if context.args else ""
    if slot not in storage.SLOTS:
        await update.message.reply_text("Nutze: /nachtrag <morning|sleep|midday|evening>")
        return
    storage.set_pending(chat_id, slot, heute_fuer(chat_id))
    await update.message.reply_text(prompts.frage(slot))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    user = storage.get_user(chat_id)
    datum = heute_fuer(chat_id)
    fertig = {e["slot"] for e in storage.entries_for_day(chat_id, datum)}
    offen = user["pending_slot"] or "—"
    anzahl = len(storage.reminders_for(chat_id))
    await update.message.reply_text(
        f"📓 {datum} ({user['tz']})\n"
        + "\n".join(f"{'✅' if s in fertig else '⬜'} {s}" for s in storage.SLOTS)
        + f"\n\nOffene Frage: {offen}\n"
        f"Zeiten: {user['t_morning']} / {user['t_midday']} / {user['t_evening']}\n"
        f"Erinnerungen: {anzahl}\n"
        f"Aktiv: {'ja' if user['aktiv'] else 'nein'}\n"
        f"Vault: {vault.VAULT_ROOT}"
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    storage.set_aktiv(chat_id, False)
    storage.set_pending(chat_id, None, None)
    schedule_user(context.application, chat_id)
    await update.message.reply_text(
        "Pausiert — ich frage nicht mehr nach dem Tag.\n"
        "Erinnerungen laufen weiter. Mit /start geht es wieder los."
    )


# ---------- Befehle: Erinnerungen ----------

HILFE_ERINNERE = (
    "⏰ Du brauchst /erinnere gar nicht — schreib einfach, was ansteht:\n\n"
    "„morgen um 9 den Arzt anrufen“\n"
    "„Freitag 16:00 Werkzeug zurueckgeben“\n"
    "„jeden Montag 18:00 Muell rausstellen“\n"
    "„taeglich 20:00 lernen“\n\n"
    "Ohne Zeitangabe schlage ich dir vier passende Zeiten vor.\n"
    "Die Formen mit klarer Uhrzeit versteht der Bot auch ohne Internet."
)


async def cmd_erinnere(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    eingabe = " ".join(context.args).strip()
    if not eingabe:
        await update.message.reply_text(HILFE_ERINNERE)
        return

    # Gleicher Weg wie bei einer normalen Nachricht: mit Zeit direkt anlegen,
    # ohne Zeit vier Vorschlaege anbieten.
    await _erinnerung_ohne_command(update, context, chat_id, eingabe)


async def cmd_erinnerungen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    liste = storage.reminders_for(chat_id)
    if not liste:
        await update.message.reply_text(
            "Keine Erinnerungen.\n\n" + HILFE_ERINNERE
        )
        return
    zeilen = [f"#{r['id']}  {reminders.beschreibe(r)}\n     „{r['text']}“" for r in liste]
    await update.message.reply_text(
        "⏰ Deine Erinnerungen:\n\n" + "\n\n".join(zeilen) + "\n\nLoeschen: /loeschen <Nummer>"
    )


async def cmd_loeschen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    storage.ensure_user(chat_id)
    try:
        rid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Nutze: /loeschen <Nummer> — Nummern zeigt /erinnerungen")
        return

    r = storage.get_reminder(rid)
    # Der Besitz-Check verhindert, dass jemand mit fremden Nummern herumraet.
    if not r or r["chat_id"] != chat_id or not r["aktiv"]:
        await update.message.reply_text(f"Erinnerung #{rid} gibt es nicht.")
        return

    storage.deactivate_reminder(rid)
    for job in context.application.job_queue.get_jobs_by_name(f"rem_{rid}"):
        job.schedule_removal()
    await update.message.reply_text(f"Geloescht: „{r['text']}“")


# ---------- Start: Zeitplaene wiederherstellen und Verpasstes nachholen ----------

async def restore_and_catch_up(application: Application):
    """Nach einem Neustart: Jobs neu setzen, Verpasstes nachholen.

    Wichtig fuer den Windows-Test: der Laptop schlaeft. Ein Job, dessen Zeit
    waehrend des Schlafs lag, feuert nicht - ohne das hier waere die Frage
    einfach weg.
    """
    for chat_id in storage.all_active_users():
        schedule_user(application, chat_id)

    # --- Erinnerungen ---
    for r in storage.all_active_reminders():
        if schedule_reminder(application, r):
            continue
        # Einmaliger Termin war faellig, waehrend der Bot aus war.
        storage.deactivate_reminder(r["id"])
        try:
            await application.bot.send_message(
                r["chat_id"], f"⏰ (verpasst, war {reminders.beschreibe(r)})\n{r['text']}"
            )
        except Exception as e:
            log.warning("Verpasste Erinnerung #%s nicht zustellbar: %s", r["id"], e)

    # --- Tagesfragen ---
    for chat_id in storage.all_active_users():
        user = storage.get_user(chat_id)
        if not user or not user["aktiv"]:
            continue
        pending, _ = storage.get_pending(chat_id)
        if pending:
            continue  # es wartet schon eine Frage - nicht doppelt fragen

        jetzt = datetime.now(tz_of(chat_id))
        datum = jetzt.strftime("%Y-%m-%d")
        erledigt = {e["slot"] for e in storage.entries_for_day(chat_id, datum)}

        faellig = [
            slot for slot in storage.GEPLANTE_SLOTS
            if slot not in erledigt
            and (jetzt.hour, jetzt.minute)
            >= tuple(int(x) for x in storage.zeit_fuer(user, slot).split(":"))
        ]
        if not faellig:
            continue

        # Nur den zuletzt faelligen fragen - drei Fragen auf einmal nerven nur.
        slot = faellig[-1]
        rest = [s for s in faellig if s != slot]
        try:
            hinweis = "Ich war kurz weg — holen wir das nach."
            if rest:
                hinweis += f"\n(Offen waeren auch: {', '.join(rest)} — /nachtrag)"
            await application.bot.send_message(chat_id, hinweis)
            storage.set_pending(chat_id, slot, datum)
            await application.bot.send_message(chat_id, prompts.frage(slot))
        except Exception as e:
            log.warning("Nachholen fuer %s fehlgeschlagen: %s", chat_id, e)

    log.info("Zeitplaene gesetzt, Verpasstes nachgeholt.")


# ---------- Start ----------

def load_api_key():
    """ANTHROPIC_API_KEY aus anthropic-key.txt nachladen, falls nicht gesetzt.

    Unter Linux kommt der Key aus ~/.lifelog.env; unter Windows ist eine Datei
    neben token.txt deutlich einfacher als dauerhafte Umgebungsvariablen.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    p = Path(__file__).with_name("anthropic-key.txt")
    if p.exists():
        key = p.read_text(encoding="utf-8").strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            log.info("API-Key aus anthropic-key.txt geladen.")


def load_token() -> str:
    token = os.environ.get("LIFELOG_TOKEN") or os.environ.get("BOT_TOKEN")
    if not token:
        tf = os.environ.get("BOT_TOKEN_FILE")
        p = Path(tf) if tf else Path(__file__).with_name("token.txt")
        if p.exists():
            token = p.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(
            "Kein Token gefunden. Setze LIFELOG_TOKEN oder lege token.txt an "
            "(Token von @BotFather)."
        )
    return token


def build_app() -> Application:
    app = (
        Application.builder()
        .token(load_token())
        .connect_timeout(20)
        .read_timeout(20)
        .get_updates_connect_timeout(20)
        .get_updates_read_timeout(40)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("zeit", cmd_zeit))
    app.add_handler(CommandHandler("zone", cmd_zone))
    app.add_handler(CommandHandler("heute", cmd_heute))
    app.add_handler(CommandHandler("nachtrag", cmd_nachtrag))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("erinnere", cmd_erinnere))
    app.add_handler(CommandHandler("erinnerungen", cmd_erinnerungen))
    app.add_handler(CommandHandler("loeschen", cmd_loeschen))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def run():
    """Expliziter Start-Ablauf - kompatibel mit Python 3.12+/3.14
    (run_polling() verlaesst sich auf asyncio.get_event_loop(), das es dort
    nicht mehr automatisch gibt)."""
    storage.init()
    load_api_key()
    log.info("Vault-Wurzel: %s", vault.VAULT_ROOT)
    if not vault.DAILY_DIR.exists():
        log.warning("Ordner 'Daily Notes' fehlt unter %s - stimmt LIFELOG_VAULT?",
                    vault.VAULT_ROOT)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY fehlt - keine Korrektur, keine "
                    "Zeiterkennung in normaler Sprache.")

    app = build_app()

    for versuch in range(1, 6):
        try:
            await app.initialize()
            break
        except (TimedOut, NetworkError) as e:
            log.warning("Telegram nicht erreichbar (Versuch %d/5): %s", versuch, e)
            await asyncio.sleep(5)
    else:
        log.error("Keine Verbindung zu Telegram. Laeuft das Internet? Abbruch.")
        return

    await restore_and_catch_up(app)
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    log.info("Bot laeuft. Mit Strg+C beenden.")
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Bot beendet.")
    except SystemExit as e:
        # SystemExit("Text") wuerde sonst kommentarlos verschluckt - dann sieht
        # man nur "beendet" und weiss nicht, dass z. B. der Token fehlt.
        if isinstance(e.code, str):
            log.error("%s", e.code)
        else:
            log.info("Bot beendet.")


if __name__ == "__main__":
    main()
