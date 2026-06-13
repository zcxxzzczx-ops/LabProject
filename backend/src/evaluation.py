"""
Modulo di valutazione: calcola metriche quantitative tra output del parser e testo Gold Standard.

Metrica obbligatoria: token_level_eval (precision, recall, F1 su insiemi di token).
Metrica aggiuntiva:   char_overlap_eval (similarita' Jaccard a livello di caratteri).
"""

import re
import mistune
from bs4 import BeautifulSoup


def rimuovi_markdown(testo_md: str) -> str:
    """
    Rimuove la sintassi Markdown da una stringa, restituendo solo testo pulito.

    Usa mistune per convertire Markdown in HTML, poi BeautifulSoup per estrarre
    il testo semplice. Approccio consigliato dalla specifica del corso (v1.1.0, slide 33)
    per evitare penalizzazioni ingiuste dovute a scelte soggettive di normalizzazione.

    Args:
        testo_md: Testo di input che puo' contenere sintassi Markdown.

    Returns:
        Testo semplice senza Markdown.
    """
    html = mistune.html(testo_md)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        tag.unwrap()
    testo = re.sub(r'[ \t]+', ' ', str(soup))
    testo = re.sub(r'\n+', '\n', testo)
    return testo.strip()


def _tokenizza(testo: str) -> set[str]:
    """
    Rimuove il Markdown dal testo, poi lo tokenizza in un insieme di token
    in minuscolo separati da spazi bianchi, come richiesto dalla specifica.
    """
    pulito = rimuovi_markdown(testo)
    return set(pulito.lower().split())


def token_level_eval(testo_parsato: str, testo_gs: str) -> dict:
    """
    Calcola precision, recall e F1 a livello di token tra testo_parsato e testo_gs.

    I token sono parole separate da spazi convertite in minuscolo.
    Si usano insiemi (ogni token unico contato una volta sola).

    Args:
        testo_parsato: Testo prodotto dal parser.
        testo_gs:      Testo di riferimento dal Gold Standard.

    Returns:
        dict con valori float per 'precision', 'recall', 'f1'.
    """
    token_estratti: set[str] = _tokenizza(testo_parsato)
    token_riferimento: set[str] = _tokenizza(testo_gs)

    intersezione: set[str] = token_estratti & token_riferimento

    precision: float = len(intersezione) / len(token_estratti) if token_estratti else 0.0
    recall: float = len(intersezione) / len(token_riferimento) if token_riferimento else 0.0

    if precision + recall > 0:
        f1: float = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def char_overlap_eval(testo_parsato: str, testo_gs: str) -> dict:
    """
    Calcola la similarita' Jaccard a livello di caratteri tra testo_parsato e testo_gs.

    Args:
        testo_parsato: Testo prodotto dal parser.
        testo_gs:      Testo di riferimento dal Gold Standard.

    Returns:
        dict con valore float per 'jaccard_similarity'.
    """
    caratteri_estratti: set[str] = set(testo_parsato.lower())
    caratteri_riferimento: set[str] = set(testo_gs.lower())

    unione = caratteri_estratti | caratteri_riferimento
    intersezione = caratteri_estratti & caratteri_riferimento

    jaccard: float = len(intersezione) / len(unione) if unione else 0.0

    return {"jaccard_similarity": round(jaccard, 4)}


def evaluate(testo_parsato: str, testo_gs: str) -> dict:
    """
    Esegue tutte le metriche di valutazione su testo_parsato vs testo_gs.

    Args:
        testo_parsato: Testo prodotto dal parser.
        testo_gs:      Testo di riferimento dal Gold Standard.

    Returns:
        dict contenente i sotto-dict 'token_level_eval' e 'char_overlap_eval'.
    """
    return {
        "token_level_eval": token_level_eval(testo_parsato, testo_gs),
        "char_overlap_eval": char_overlap_eval(testo_parsato, testo_gs),
    }
