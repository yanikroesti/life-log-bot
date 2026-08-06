# Life Log — Tagesprotokoll + Erinnerungen

Ein Telegram-Bot, der dreimal am Tag nachfragt, wie dein Tag läuft. Deine Antwort wird auf Tippfehler korrigiert, formatiert und als Abschnitt **direkt in deine Daily Note** geschrieben. Dazu Erinnerungen in normaler Sprache.

Warum: die `Daily Notes` sind Ende Juni eingeschlafen. Das Format war gut — es hat nur die Erinnerung gefehlt.

---

## Tagesprotokoll

| Zeit | Was der Bot fragt | Abschnitt in der Daily Note |
|---|---|---|
| 07:00 | Wie war dein Morgen bisher? | `## Morning Routine` |
| direkt danach | Wie hast du geschlafen? | `## Sleep` |
| 12:15 | Wie fühlst du dich, was ist der Plan? | `## Midday` |
| 21:00 | Was hast du geschafft, wie geht's dir, Plan für morgen? | `## Evening` |

Die Schlaf-Frage hat **keinen eigenen Timer** — sie kommt direkt nach deiner Morgen-Antwort im selben Gespräch. Eine Benachrichtigung, zwei Abschnitte.

Du antwortest ganz normal. Tippfehler sind egal, genau dafür ist die Korrektur da.

### Jederzeit von dir aus schreiben

Du musst nicht auf eine Frage warten. Schreib dem Bot einfach spontan — er ordnet die Nachricht selbst ein:

- klingt es nach deinem Tag → landet im passenden Abschnitt (Morgen / Schlaf / Mittag / Abend), erkannt aus **Inhalt** und Uhrzeit („schlecht geschlafen" geht auch mittags unter *Sleep*)
- klingt es nach einem Termin → wird zur Erinnerung (siehe unten)
- ist es ein Gruss oder eine Frage → kurze Hilfe

Der Bot bestätigt dir, in welchen Abschnitt es ging. Lag er daneben, `/nachtrag <slot>` und die nächste Nachricht geht gezielt dorthin.

### Wo es landet

Alles in **einer** Datei pro Tag: `Daily Notes/2026-07-20.md`, neben dem, was du selbst hineinschreibst.

```markdown
# 2026-07-20

## What I Did

- Was du selbst notiert hast

## Morning Routine

*07:12*

- Went for a 6 km run
- Coffee and some reading

## Sleep

*07:15*

- About 7 hours, decent quality
```

> **Diese Datei bearbeitest du auch von Hand.** Solange die Slots in ihrer natürlichen Reihenfolge über den Tag kommen, wird ausschliesslich **angehängt** — bestehende Zeilen werden nie angefasst. Nur wenn du etwas ausser der Reihe nachträgst (abends noch `/nachtrag morning`), muss mitten in der Datei eingefügt werden; davor legt der Bot automatisch eine Kopie unter `backups/` an.

---

## Erinnerungen — ohne Befehl

Schreib einfach, was ansteht. Der Bot erkennt selbst, dass es ein Termin ist:

```
morgen um 9 den Arzt anrufen
Freitag 16:00 Werkzeug zurückgeben
jeden Montag 18:00 Müll rausstellen
täglich 20:00 lernen
```

Steht eine Zeit dabei, legt er sie direkt an und bestätigt mit einer Nummer zum Löschen.

### Ohne Zeitangabe: vier Vorschläge

Schreibst du nur *„ich muss noch den Arzt anrufen"*, fragt er nach — mit vier Zeiten, die zu **dieser Aufgabe** passen:

```
⏰ Wann soll ich dich erinnern?
„den Arzt anrufen"

[ 14:00 · gleich nachher ]   [ 16:00 · Praxiszeit ]
[ morgen 08:30 · vor Arbeit ][ morgen 17:00 · nach Feierabend ]
[ 📓 Kein Termin — ins Tagebuch ]
```

Ein Tipp genügt. Passt keine, schreib die Zeit einfach hin („um 17:30"). Und lag der Bot daneben und es war gar kein Termin, schiebt der letzte Knopf es als Tagebuch-Eintrag in die Notiz.

Die Vorschläge richten sich nach der Aufgabe, nicht nach runden Uhrzeiten: Arztpraxis → Öffnungszeiten, Müll → abends, Sport → vor oder nach der Arbeit. Nachtstunden schlägt er nie vor, und alle Zeiten liegen garantiert in der Zukunft.

**Intern:** feste Formate (`YYYY-MM-DD HH:MM …`, `täglich HH:MM …`, `montags HH:MM …`) erkennt der Bot per Muster — kostenlos und ohne Internet. Alles andere geht an Claude Haiku. Was zurückkommt, wird in Python nachgeprüft: ein halluziniertes `2026-13-45` oder ein Vorschlag in der Vergangenheit kommt nie durch. Ohne Internet gibt es generische Vorschlagszeiten statt gar keiner.

---

## Befehle

| Befehl | Wirkung |
|---|---|
| `/start` | Einschalten, Zeitplan setzen |
| `/erinnere …` | Erinnerung anlegen (geht auch ohne den Befehl) |
| `/erinnerungen` | Alle Erinnerungen mit Nummer |
| `/loeschen 3` | Erinnerung löschen |
| `/zeit morning 06:45` | Uhrzeit für `morning`, `midday` oder `evening` |
| `/zone utc` | Zeitzone (Standard `Europe/Zurich`) |
| `/heute` | Was heute schon drinsteht |
| `/nachtrag evening` | Einen Slot nachträglich ausfüllen |
| `/status` | Fertige Slots, offene Frage, Vault-Pfad |
| `/stop` | Fragen pausieren (Erinnerungen laufen weiter) |

---

## Wenn der Rechner geschlafen hat

Ein Timer, dessen Zeit während des Ruhezustands lag, feuert nicht. Deshalb holt der Bot beim Start nach:

- **Verpasste Erinnerungen** kommen mit dem Vermerk `(verpasst, war …)`.
- **Verpasste Tagesfragen:** der Bot stellt die *zuletzt* fällige und nennt die anderen — drei Fragen auf einmal wären nur nervig.
- Wartet schon eine Frage auf Antwort, fragt er **nicht** nochmal.

Das ist der Grund, warum der Testbetrieb auf dem Windows-Laptop überhaupt brauchbar ist.

---

## Aufbau

| Datei | Aufgabe |
|---|---|
| `bot.py` | Zeitplan, Gesprächsablauf, Befehle, Nachhol-Logik |
| `prompts.py` | Die vier Slots: Frage, Überschrift, Fokus für die KI |
| `polish.py` | Rechtschreibkorrektur mit Claude Haiku 4.5 |
| `reminders.py` | Zeitangaben verstehen (Muster + Haiku) |
| `route.py` | Spontane Nachrichten einordnen (Eintrag / Erinnerung / anderes) |
| `vault.py` | Abschnitte in die Daily Note schreiben |
| `storage.py` | SQLite: Benutzer, Zeiten, offene Frage, Einträge, Erinnerungen |
| `start-lifelog.bat` | Start unter Windows |
| `lifelog.service` | systemd-Unit fürs EliteBook |
| `Setup.md` | Installation Windows und Linux |

Die Engine ist eine Variante des [Stromtraining-Bots](../../Career/Apprenticeship/Stromtraining/README.md) — gleiche Bibliothek (`python-telegram-bot[job-queue]==21.6`), gleicher Python-3.14-sicherer Startablauf, gleiche Zeitzonen-Logik.

**Ein Unterschied ist wichtig:** Stromtraining merkt sich die laufende Frage im Arbeitsspeicher. Bei einem Quiz ist das egal. Hier können zwischen Frage und Antwort Stunden liegen — deshalb steht die offene Frage in der **Datenbank**. Ein Neustart verliert nichts.

---

## Wenn etwas ausfällt

Ein Eintrag geht **nie** verloren:

| Ausfall | Was passiert |
|---|---|
| Claude nicht erreichbar / kein API-Key | Rohtext wird gespeichert, markiert mit `⚠️ (unpolished)` |
| Claude nicht erreichbar bei Erinnerungen | Feste Formate gehen weiter; Vorschläge werden generisch statt aufgabenbezogen |
| Vault-Ordner weg | Text liegt in `lifelog.db`, Telegram meldet den Fehler |
| Neustart | Offene Frage überlebt, Antwort landet im richtigen Slot |
| Antwort erst nach Mitternacht | Eintrag geht zum Tag, an dem gefragt wurde |

Jede Antwort liegt in **zwei** unabhängigen Orten: als Rohtext in `lifelog.db` und als Markdown in der Daily Note.

---

## Kosten

Vier Einträge am Tag plus ein paar Erinnerungen über Claude Haiku 4.5 ($1 / $5 pro Mio. Token) — grob **0.15–0.25 CHF im Monat**.

---

## Betrieb

Aktuell im **Testbetrieb auf Windows** (siehe [Setup.md](Setup.md)). Sobald das EliteBook verfügbar ist, zieht er dorthin um und läuft als systemd-Dienst neben `stromtraining` und `deutsch-b1` — ein neuer Server ist nicht nötig.
