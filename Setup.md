# Setup

Zwei Teile: **jetzt** Testbetrieb auf Windows, **später** Umzug aufs EliteBook.

---

# Teil A — Testbetrieb auf Windows (jetzt)

Auf Windows ist es einfacher als auf dem Server: der Bot liegt **im** Vault und findet ihn von allein. Der Sync (Obsidian remotely-save → Dropbox) ist bereits eingerichtet und läuft — hier ist nichts mehr zu tun.

Alle Pfade unten gehen von deiner echten Vault-Wurzel aus:

```
C:\Users\yanik\Documents\Obsidian Vault\Life\Life Log
```

Der Haken: **der Laptop schläft.** Ist er um 07:00 aus, kommt keine Nachricht. Dafür holt der Bot beim nächsten Start nach, was fällig gewesen wäre. Für eine Woche Test reicht das gut.

## A1 — Telegram-Bot anlegen

In Telegram zu **@BotFather**:

```
/newbot
Name:     Life Log
Username: irgendwas_lifelog_bot
```

Den Token, den du zurückbekommst, in eine Datei legen — **du machst das selbst, ich fasse deine Tokens nicht an**:

1. Explorer öffnen → `C:\Users\yanik\Documents\Obsidian Vault\Life\Life Log`
2. Neue Textdatei `token.txt` anlegen
3. Nur den Token hineinschreiben, sonst nichts, speichern

Ein **eigener** Bot, nicht `@School_yanik_bot` mitbenutzen — sonst mischen sich Lernfragen und Tagebuch im selben Chat.

## A2 — Anthropic-API-Key

Key holen auf <https://console.anthropic.com> → API Keys → Create Key.

Im selben Ordner (`C:\Users\yanik\Documents\Obsidian Vault\Life\Life Log`) eine Datei `anthropic-key.txt` anlegen und den Key hineinschreiben.

> Ohne Key startet der Bot trotzdem. Dann werden Einträge nicht korrigiert (`⚠️ unpolished`) und `/erinnere` versteht nur die festen Formate wie `2026-07-25 09:00 Arzt anrufen`.

> ⚠️ **Der Ordner liegt im Vault, und der Vault synct nach Dropbox.** `token.txt` und `anthropic-key.txt` landen damit in deiner Dropbox und auf jedem Gerät, auf dem der Vault liegt. Bei `token.txt` machst du das bei den Lern-Bots schon so; beim API-Key ist es heikler, weil er Geld kosten kann.
>
> Willst du den Key aus dem Vault heraushalten, setz stattdessen eine Windows-Umgebungsvariable und lass `anthropic-key.txt` weg:
> ```
> setx ANTHROPIC_API_KEY "sk-ant-..."
> ```
> Danach ein **neues** Terminal öffnen (bestehende sehen die Variable nicht). Der Bot bevorzugt immer die Umgebungsvariable und liest die Datei nur, wenn keine gesetzt ist.
>
> Falls ein Key doch mal abhandenkommt: in der Anthropic-Console widerrufen und einen neuen erstellen.

## A3 — Paket installieren

Ist bereits erledigt: `anthropic 0.117.0` und `python-telegram-bot 21.6` sind auf diesem Rechner installiert. Falls es doch mal fehlt:

```
python -m pip install -r requirements.txt
```

## A4 — Starten

**Doppelklick auf `start-lifelog.bat`.**

Erwartete Ausgabe:

```
INFO lifelog - Vault-Wurzel: C:\Users\yanik\Documents\Obsidian Vault
INFO lifelog - API-Key aus anthropic-key.txt geladen.
INFO lifelog - Zeitplaene gesetzt, Verpasstes nachgeholt.
INFO lifelog - Bot laeuft. Mit Strg+C beenden.
```

Steht dort stattdessen `Kein Token gefunden`, fehlt `token.txt` oder sie liegt im falschen Ordner.

**Das Fenster offen lassen** — schliessen beendet den Bot.

## A5 — Abnahme (10 Minuten)

1. In Telegram `/start` → Begrüssung mit deinen drei Uhrzeiten.
2. `/zeit morning HH:MM` auf **zwei Minuten in der Zukunft** setzen. Warten.
3. Antworten, ruhig mit Tippfehlern. Es muss:
   - eine korrigierte Fassung erscheinen,
   - **direkt danach die Schlaf-Frage** kommen.
4. Schlaf-Frage beantworten.
5. In Obsidian die heutige Daily Note öffnen → `## Morning Routine` und `## Sleep` stehen drin.
6. **Spontan schreiben:** ohne dass eine Frage offen ist, dem Bot etwas über deinen Tag schicken (z. B. „gerade 6 km gelaufen"). Er muss bestätigen, unter welchen Abschnitt es ging, und es steht in der Daily Note.
7. **Erinnerung ohne Befehl:** `in 2 minuten testen ob das klappt` schreiben (ohne `/erinnere`) → Bestätigung lesen, warten, `⏰` muss kommen.
8. **Vorschläge:** `ich muss noch den arzt anrufen` schreiben → vier Zeit-Knöpfe müssen erscheinen, einen antippen, Bestätigung prüfen.
9. `taeglich 20:00 lernen` → `/erinnerungen` zeigt alle, `/loeschen <Nr>` entfernt eine.
10. **Neustart-Test:** `/nachtrag evening` schicken, *nicht* antworten, Fenster mit `Strg+C` schliessen, `start-lifelog.bat` neu starten, dann erst antworten. Der Text muss unter `## Evening` landen.
11. **Schlaf-Test:** Laptop zuklappen, eine Slot-Zeit überspringen lassen, aufklappen, Bot neu starten → er fragt die verpasste Frage nach.

## A6 — Automatisch mitstarten (optional)

Damit du nicht jedes Mal doppelklicken musst:

1. **Aufgabenplanung** öffnen (Windows-Suche: „Aufgabenplanung")
2. Rechts → **Einfache Aufgabe erstellen**
3. Name: `Life Log Bot`
4. Trigger: **Beim Anmelden**
5. Aktion: **Programm starten**
   - Programm: `pythonw.exe` — den vollen Pfad findest du mit `python -c "import sys;print(sys.executable.replace('python.exe','pythonw.exe'))"`
   - Argumente: `bot.py`
   - Starten in: `C:\Users\yanik\Documents\Obsidian Vault\Life\Life Log`
6. Fertigstellen → Eigenschaften → Haken bei **Unabhängig von der Benutzeranmeldung ausführen** *nicht* setzen (der Bot braucht dein Benutzerprofil)

`pythonw.exe` statt `python.exe` heisst: kein Konsolenfenster. Zum Debuggen wieder `start-lifelog.bat` nehmen — da siehst du die Logs.

Beenden: Task-Manager → `pythonw.exe`.

---

# Teil B — Umzug aufs EliteBook (in ~einer Woche)

Kein neuer Server nötig: das EliteBook 8460p (Xubuntu) läuft schon durch und hostet `stromtraining` und `deutsch-b1`. Der Life-Log-Bot kommt als dritter Dienst dazu.

Der Vault liegt auf dem EliteBook unter — genau wie deine anderen Bots:

```
/home/yanik/Documents/Obsidian Vault/Life/Life Log
```

Der Sync ist eingerichtet, daran ist nichts zu tun. Nur eins im Hinterkopf behalten: **damit ein Eintrag von 21:00 auch wirklich rausgeht, muss das laufen, was du für den Sync eingerichtet hast** (Dropbox-Daemon bzw. Obsidian auf dem EliteBook). Läuft es nur zeitweise, kommt der Eintrag eben beim nächsten Mal mit — verloren geht nichts, er liegt zusätzlich in `lifelog.db`.

## B1 — Zugangsdaten

`token.txt` und `anthropic-key.txt` kommen über den Sync automatisch mit. Absichern und den API-Key zusätzlich für den Dienst ablegen:

```bash
cd "/home/yanik/Documents/Obsidian Vault/Life/Life Log"
chmod 600 token.txt anthropic-key.txt

printf 'ANTHROPIC_API_KEY=sk-ant-api03-DEIN_KEY\nLIFELOG_ALLOWED=DEINE_CHAT_ID\n' > ~/.lifelog.env
chmod 600 ~/.lifelog.env
```

Der Key gehört **nicht** in die systemd-Unit: Dateien unter `/etc/systemd/system/` sind für alle lesbar, `systemctl cat lifelog` würde ihn im Klartext zeigen.

> ⚠️ **`LIFELOG_ALLOWED` nicht vergessen.** Ohne diese Zeile kann jeder, der den Bot in Telegram findet, `/start` drücken — und seine Antworten landen in *deiner* Daily Note. Deine chat_id siehst du im Log, sobald du `/start` schickst. Format wie beim Key: Name, `=`, Wert — keine Leerzeichen, keine Anführungszeichen.

## B2 — Python-Umgebung

Eigenes venv, getrennt von `~/.lernbot-venv`, damit ein Update hier die Lern-Bots nicht umwirft:

```bash
sudo apt install -y python3 python3-venv python3-pip

python3 -m venv ~/.lifelog-venv
~/.lifelog-venv/bin/python -m pip install --upgrade pip
~/.lifelog-venv/bin/python -m pip install -r \
  "/home/yanik/Documents/Obsidian Vault/Life/Life Log/requirements.txt"
```

Von Hand testen:

```bash
cd "/home/yanik/Documents/Obsidian Vault/Life/Life Log"
set -a; source ~/.lifelog.env; set +a
~/.lifelog-venv/bin/python bot.py
```

**Prüf die Vault-Wurzel in der ersten Log-Zeile** — sie muss `/home/yanik/Documents/Obsidian Vault` sein.

## B3 — Als Dienst einrichten

`lifelog.service` liegt in diesem Ordner und zeigt schon auf `/home/yanik/Documents/Obsidian Vault/...` — kurz prüfen, dann:

```bash
sudo cp lifelog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lifelog
systemctl status lifelog
journalctl -u lifelog -f
```

## B4 — Windows abschalten

Wichtig: **nicht beide gleichzeitig laufen lassen.** Zwei Bots mit demselben Token holen sich gegenseitig die Nachrichten weg — Telegram liefert jedes Update nur einmal aus.

Auf Windows also: Aufgabenplanung → Aufgabe `Life Log Bot` deaktivieren, und `pythonw.exe` im Task-Manager beenden.

Die `lifelog.db` mit deinen bisherigen Einträgen kommt über den Sync mit — Zeiten, Erinnerungen und Historie sind auf dem EliteBook sofort wieder da.

---

## Wartung

```bash
systemctl status lifelog             # läuft er?
journalctl -u lifelog -f             # live mitlesen
journalctl -u lifelog --since today  # heutige Fehler
sudo systemctl restart lifelog       # nach Code-Änderungen
```

Nach Änderungen am Code muss neu gestartet werden — Python-Dateien werden nicht von selbst nachgeladen.

---

## Wenn etwas klemmt

| Symptom | Ursache | Fix |
|---|---|---|
| `Kein Token gefunden` | `token.txt` fehlt oder falscher Ordner | Datei neben `bot.py` legen |
| Keine Nachricht zur eingestellten Zeit | Rechner hat geschlafen | Bot neu starten, er holt nach |
| Falsche Uhrzeit | Zeitzone | `/status` zeigt Zone und Zeiten, `/zone zurich` |
| Alles trägt `⚠️ (unpolished)` | Kein/ungültiger API-Key | Log nach `Claude` durchsuchen |
| `/erinnere` versteht nichts | Kein API-Key → nur feste Formate | `/erinnere 2026-07-25 09:00 Text` |
| Einträge kommen nicht aufs Handy | Obsidian zu / remotely-save nicht gelaufen | Obsidian öffnen, Sync auslösen |
| Bot antwortet doppelt | Windows **und** Server laufen gleichzeitig | Einen von beiden stoppen |
| Umlaute kaputt in der Konsole | Codepage | `start-lifelog.bat` setzt das schon; nicht direkt `python bot.py` in cmd |
