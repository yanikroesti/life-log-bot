@echo off
REM Life Log Bot unter Windows starten (Testbetrieb).
REM Doppelklick genuegt. Das Fenster offen lassen - schliessen beendet den Bot.

cd /d "%~dp0"

REM Konsole auf UTF-8, sonst brechen Emoji und Umlaute in den Logs ab.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM Token und API-Key liest der Bot selbst aus token.txt und anthropic-key.txt.
REM LIFELOG_VAULT wird NICHT gesetzt: der Bot liegt im Vault und findet ihn
REM dadurch von allein (zwei Ordner hoeher).

echo ================================
echo  Life Log Bot
echo  Beenden mit Strg+C
echo ================================
echo.

python bot.py

echo.
echo Bot beendet. Fenster kann geschlossen werden.
pause
