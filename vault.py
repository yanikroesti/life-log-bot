"""Schreibt die Eintraege als Abschnitte direkt in die Daily Note.

    Daily Notes/YYYY-MM-DD.md

Diese Datei bearbeitest DU auch von Hand. Darum die Grundregel:

  Solange die Slots in ihrer natuerlichen Reihenfolge ueber den Tag kommen
  (morning -> sleep -> midday -> evening), wird ausschliesslich ANGEHAENGT.
  Bestehende Bytes werden dabei nie angefasst.

Nur wenn du etwas ausser der Reihe nachtraegst (z. B. abends noch /nachtrag
morning), muss mitten in der Datei eingefuegt werden. Davor legt der Bot
automatisch eine Sicherungskopie unter Life/Life Log/backups/ an.
"""
import logging
import os
from datetime import datetime
from pathlib import Path

import prompts

log = logging.getLogger("lifelog.vault")

# Diese Datei liegt in  <Vault>/Life/Life Log/  ->  zwei Ebenen hoch ist der Vault.
# Auf einem Server zeigt LIFELOG_VAULT auf den synchronisierten Ordner.
VAULT_ROOT = Path(os.environ.get("LIFELOG_VAULT") or Path(__file__).resolve().parents[2])

DAILY_DIR = VAULT_ROOT / "Daily Notes"
BACKUP_DIR = Path(__file__).resolve().parent / "backups"


def heute(tz=None) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


def pfad_fuer(datum: str) -> Path:
    return DAILY_DIR / f"{datum}.md"


def _block(zeitstempel: str, text: str) -> list[str]:
    return [f"*{zeitstempel}*", "", *text.splitlines()]


def _sichern(pfad: Path):
    """Kopie anlegen, bevor mitten in einer Datei editiert wird."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    ziel = BACKUP_DIR / f"{pfad.stem}-{stempel}.md"
    ziel.write_text(pfad.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    log.info("Sicherung: %s", ziel)


def append(slot: str, text: str, datum: str | None = None, zeit: str | None = None) -> Path:
    """Einen Eintrag als Abschnitt in die Daily Note schreiben."""
    datum = datum or heute()
    zeitstempel = zeit or datetime.now().strftime("%H:%M")
    ueberschrift = prompts.ueberschrift(slot)
    pfad = pfad_fuer(datum)

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    # --- Datei gibt es noch nicht: neu anlegen ---
    if not pfad.exists():
        inhalt = "\n".join([f"# {datum}", "", ueberschrift, "", *_block(zeitstempel, text)])
        with open(pfad, "w", encoding="utf-8", newline="\n") as f:
            f.write(inhalt.rstrip() + "\n")
        return pfad

    roh = pfad.read_text(encoding="utf-8")
    zeilen = roh.splitlines()
    ueberschriften = [i for i, z in enumerate(zeilen) if z.startswith("## ")]

    # --- Datei ist leer (kommt vor: Obsidian legt leere Daily Notes an) ---
    if not roh.strip():
        inhalt = "\n".join([f"# {datum}", "", ueberschrift, "", *_block(zeitstempel, text)])
        with open(pfad, "w", encoding="utf-8", newline="\n") as f:
            f.write(inhalt.rstrip() + "\n")
        return pfad

    hat_abschnitt = ueberschrift in zeilen
    ist_letzter = bool(ueberschriften) and zeilen[ueberschriften[-1]] == ueberschrift

    # --- Normalfall: reines Anhaengen, bestehende Bytes bleiben unberuehrt ---
    if not hat_abschnitt or ist_letzter:
        teile = [] if ist_letzter else [ueberschrift, ""]
        teile += _block(zeitstempel, text)
        # prefix schliesst die letzte Zeile ab, falls die Datei ohne \n endet;
        # das zweite \n ist die Leerzeile vor dem neuen Block.
        prefix = "" if roh.endswith("\n") else "\n"
        with open(pfad, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{prefix}\n" + "\n".join(teile) + "\n")
        return pfad

    # --- Ausnahme: Nachtrag ausser der Reihe -> mitten einfuegen, vorher sichern ---
    _sichern(pfad)
    start = zeilen.index(ueberschrift) + 1
    ende = len(zeilen)
    for i in range(start, len(zeilen)):
        if zeilen[i].startswith("## "):
            ende = i
            break
    while ende > start and not zeilen[ende - 1].strip():
        ende -= 1
    zeilen[ende:ende] = ["", *_block(zeitstempel, text)]
    pfad.write_text("\n".join(zeilen).rstrip() + "\n", encoding="utf-8", newline="\n")
    return pfad


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = append("morning", "- went for a 6 km run\n- coffee and some reading", zeit="07:12")
    print(f"geschrieben: {p}\n")
    print(p.read_text(encoding="utf-8"))
