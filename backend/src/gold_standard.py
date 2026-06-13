"""
Caricatore del Gold Standard: legge i file JSON GS dalla cartella gs_data/.
Ogni file si chiama <slug_dominio>_gs.json e contiene una lista di entry GS.
"""

import json
import os
from pathlib import Path


# Percorso della cartella gs_data/ rispetto alla posizione di questo file
_CARTELLA_GS = Path(os.getenv("GS_DATA_DIR", str(Path("/app/gs_data"))))


def _dominio_a_slug(dominio: str) -> str:
    """Converte una stringa dominio in slug sicuro per nome file, es. 'en.wikipedia.org' -> 'en_wikipedia_org'."""
    return dominio.replace(".", "_").replace("-", "_")


def _carica_file_gs(dominio: str) -> list[dict]:
    """
    Carica il file JSON Gold Standard per il dominio indicato.

    Args:
        dominio: Stringa dominio canonica (es. 'en.wikipedia.org').

    Returns:
        Lista di dict rappresentanti le entry GS.

    Raises:
        FileNotFoundError: Se non esiste il file GS per il dominio.
    """
    slug = _dominio_a_slug(dominio)
    percorso = _CARTELLA_GS / f"{slug}_gs.json"
    if not percorso.exists():
        raise FileNotFoundError(f"Nessun file Gold Standard trovato per il dominio '{dominio}' in {percorso}")
    with open(percorso, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_full_gold_standard(dominio: str) -> list[dict]:
    """
    Restituisce tutte le entry GS per un dato dominio.

    Args:
        dominio: Stringa dominio supportata.

    Returns:
        Lista di dict rappresentanti le entry GS.

    Raises:
        FileNotFoundError: Se il file GS e' assente.
    """
    return _carica_file_gs(dominio)


def get_gold_standard_by_url(url: str, dominio: str) -> dict:
    """
    Restituisce la singola entry GS corrispondente all'URL indicato.

    Args:
        url:     L'URL esatto da cercare.
        dominio: Il dominio a cui appartiene l'URL.

    Returns:
        Il dict della entry GS corrispondente.

    Raises:
        FileNotFoundError: Se il file GS e' assente.
        KeyError: Se l'URL non e' presente nel GS.
    """
    entries = _carica_file_gs(dominio)
    for entry in entries:
        if entry.get("url") == url:
            return entry
    raise KeyError(f"URL '{url}' non trovato nel Gold Standard per il dominio '{dominio}'")
