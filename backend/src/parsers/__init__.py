"""
Router dei parser: dato un URL (o URL + html_text), seleziona ed esegue
il parser corretto per il dominio.
"""

from urllib.parse import urlparse

from .wikipedia_parser import parse as _parse_wikipedia, parse_html as _parse_html_wikipedia
from .meteoam_parser import parse as _parse_meteoam, parse_html as _parse_html_meteoam
from .rottentomatoes_parser import parse as _parse_rottentomatoes, parse_html as _parse_html_rottentomatoes
from .wunderground_parser import parse as _parse_wunderground, parse_html as _parse_html_wunderground

# Mappa ogni dominio supportato alla coppia di funzioni (parse, parse_html)
_MAPPA_PARSER: dict = {
    "en.wikipedia.org": (_parse_wikipedia, _parse_html_wikipedia),
    "www.meteoam.it": (_parse_meteoam, _parse_html_meteoam),
    "meteoam.it": (_parse_meteoam, _parse_html_meteoam),
    "editorial.rottentomatoes.com": (_parse_rottentomatoes, _parse_html_rottentomatoes),
    "www.wunderground.com": (_parse_wunderground, _parse_html_wunderground),
    "wunderground.com": (_parse_wunderground, _parse_html_wunderground),
}

# Nomi canonici dei domini (come restituiti da GET /domains)
SUPPORTED_DOMAINS: list[str] = [
    "en.wikipedia.org",
    "www.meteoam.it",
    "editorial.rottentomatoes.com",
    "www.wunderground.com",
]


def get_domain(url: str) -> str:
    """Estrae il netloc (dominio) da una stringa URL."""
    return urlparse(url).netloc


def is_supported(url: str) -> bool:
    """Restituisce True se il dominio dell'URL e' gestito da uno dei parser."""
    return get_domain(url) in _MAPPA_PARSER


async def parse(url: str) -> dict:
    """
    Indirizza un URL al parser appropriato e restituisce il risultato.
    Scarica la pagina dalla rete.

    Args:
        url: Qualsiasi URL il cui dominio e' supportato.

    Returns:
        Dict del documento parsato (url, domain, title, html_text, parsed_text).

    Raises:
        ValueError:   Se il dominio non e' supportato.
        RuntimeError: Se il crawling fallisce.
    """
    dominio = get_domain(url)
    coppia_parser = _MAPPA_PARSER.get(dominio)
    if coppia_parser is None:
        raise ValueError(f"Il dominio '{dominio}' non e' supportato")
    return await coppia_parser[0](url)


async def parse_html(url: str, html_text: str) -> dict:
    """
    Indirizza al parser appropriato usando html_text fornito (senza chiamata di rete).
    Usa internamente il prefisso raw: di Crawl4AI.

    Args:
        url:       URL originale, usato per selezionare il parser corretto.
        html_text: Contenuto HTML grezzo da analizzare direttamente.

    Returns:
        Dict del documento parsato (url, domain, title, html_text, parsed_text).

    Raises:
        ValueError: Se il dominio non e' supportato.
    """
    dominio = get_domain(url)
    coppia_parser = _MAPPA_PARSER.get(dominio)
    if coppia_parser is None:
        raise ValueError(f"Il dominio '{dominio}' non e' supportato")
    return await coppia_parser[1](url, html_text)
