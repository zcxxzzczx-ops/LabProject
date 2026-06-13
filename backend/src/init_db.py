"""
Script di inizializzazione del database.

Eseguito automaticamente all'avvio del container backend (prima di uvicorn).
Crea le tabelle se non esistono e carica i file Gold Standard dalla cartella
gs_data/ nel database, popolando web_resources e gold_standard.

Operazione idempotente: eseguire più volte non crea duplicati grazie a
INSERT ... ON DUPLICATE KEY UPDATE.
"""

import json
import logging
import os
import time
from pathlib import Path

import mariadb

from database import init_schema, insert_web_resource, insert_gold_standard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INIT] %(message)s")
log = logging.getLogger(__name__)

_GS_DIR = Path(os.getenv("GS_DATA_DIR", "/app/gs_data"))


def _attendi_db(max_tentativi: int = 30, pausa: float = 2.0) -> None:
    """Attende che MariaDB sia pronto prima di procedere."""
    from database import _DB_CONFIG
    config_senza_autocommit = {k: v for k, v in _DB_CONFIG.items() if k != "autocommit"}
    for tentativo in range(1, max_tentativi + 1):
        try:
            conn = mariadb.connect(**config_senza_autocommit)
            conn.close()
            log.info("MariaDB pronto dopo %d tentativo/i.", tentativo)
            return
        except mariadb.Error as exc:
            log.info("Tentativo %d/%d: DB non pronto (%s). Attendo %.0fs...",
                     tentativo, max_tentativi, exc, pausa)
            time.sleep(pausa)
    raise RuntimeError("MariaDB non raggiungibile dopo i tentativi massimi.")


def _carica_file_gs(percorso: Path) -> None:
    """Carica un singolo file GS JSON nel database."""
    log.info("Carico %s ...", percorso.name)
    with open(percorso, encoding="utf-8") as fh:
        entries: list[dict] = json.load(fh)

    inserite = 0
    for entry in entries:
        url = entry.get("url", "").strip()
        domain = entry.get("domain", "").strip()
        title = entry.get("title", "").strip()
        html_text = entry.get("html_text", "")
        gold_text = entry.get("gold_text", "")

        if not url or not domain:
            log.warning("Entry senza url/domain saltata: %s", entry)
            continue

        # Prima inserisce la web_resource (tabella padre)
        insert_web_resource(url, domain, title, html_text)
        # Poi inserisce il gold_standard (tabella figlia)
        insert_gold_standard(url, gold_text)
        inserite += 1

    log.info("  → %d entry caricate da %s", inserite, percorso.name)


def main() -> None:
    """Entry point dello script di inizializzazione."""
    log.info("=== Inizializzazione database ===")

    _attendi_db()

    log.info("Creazione schema (se non esiste)...")
    init_schema()
    log.info("Schema OK.")

    if not _GS_DIR.exists():
        log.warning("Cartella gs_data/ non trovata in %s. Nessun GS caricato.", _GS_DIR)
        return

    file_gs = sorted(_GS_DIR.glob("*_gs.json"))
    if not file_gs:
        log.warning("Nessun file *_gs.json trovato in %s.", _GS_DIR)
        return

    for percorso in file_gs:
        try:
            _carica_file_gs(percorso)
        except Exception as exc:
            log.error("Errore caricando %s: %s", percorso.name, exc)

    log.info("=== Inizializzazione completata ===")


if __name__ == "__main__":
    main()
