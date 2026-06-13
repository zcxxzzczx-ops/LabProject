"""
Parser per www.meteoam.it (Servizio Meteorologico dell'Aeronautica Militare Italiana).
Estrae testo di bollettini/previsioni dalle pagine meteo.
"""

import re
import asyncio
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


# Selettore primario: testo editoriale dell'articolo
_SELETTORE_PRIMARIO_METEOAM = ".editor-wcs-text"
# Selettore di fallback: sezione principale quando il primario non produce risultati
_SELETTORE_FALLBACK_METEOAM = "#details_news_page, .news-details-main-col, main"

_TAG_ESCLUSI_METEOAM = [
    "script", "style", "noscript",
    ".editor-wcs-image-container",
    ".editor-wcs-image-row",
    ".editor-wcs-figure",
    "nav", "footer", "header",
    ".breadcrumb", ".menu", ".navbar",
    "#cookie-bar", ".cookie-notice",
]


def _url_appartiene_a_meteoam(url: str) -> bool:
    """Restituisce True se l'URL appartiene a www.meteoam.it."""
    return urlparse(url).netloc in ("www.meteoam.it", "meteoam.it")


def _pulisci_markdown_meteoam(md_grezzo: str) -> str:
    """Pulisce il Markdown grezzo dalle pagine meteoam.it."""
    testo = re.sub(r"!\[.*?\]\(.*?\)", "", md_grezzo)
    testo = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", testo)
    testo = re.sub(r"<!--.*?-->", "", testo, flags=re.DOTALL)
    righe = testo.splitlines()
    righe_pulite = [ln for ln in righe if len(ln.strip()) >= 3 or ln.strip() == ""]
    testo = "\n".join(righe_pulite)
    testo = re.sub(r"\n{3,}", "\n\n", testo)
    return testo.strip()


def _crea_config_crawler(selettore_css: str) -> CrawlerRunConfig:
    """Costruisce una CrawlerRunConfig per le pagine Meteoam con il selettore indicato."""
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        css_selector=selettore_css,
        excluded_tags=_TAG_ESCLUSI_METEOAM,
        remove_overlay_elements=True,
        wait_until="networkidle",
        word_count_threshold=5,
    )


async def _crawla_con_fallback(target: str) -> str:
    """
    Esegue il crawl di target (URL o stringa raw:<html>) provando prima il selettore primario.
    Passa al selettore di fallback se il primario non produce testo.

    Args:
        target: URL o stringa 'raw:<html>' per Crawl4AI.

    Returns:
        Testo Markdown pulito (puo' essere stringa vuota se non si trova nulla).
    """
    cfg_browser = BrowserConfig(headless=True)

    async with AsyncWebCrawler(config=cfg_browser) as crawler:
        risultato = await crawler.arun(
            url=target,
            config=_crea_config_crawler(_SELETTORE_PRIMARIO_METEOAM),
        )

    md_grezzo = (risultato.markdown or "") if risultato.success else ""
    testo_parsato = _pulisci_markdown_meteoam(md_grezzo)

    if not testo_parsato:
        async with AsyncWebCrawler(config=cfg_browser) as crawler:
            risultato = await crawler.arun(
                url=target,
                config=_crea_config_crawler(_SELETTORE_FALLBACK_METEOAM),
            )
        md_grezzo = (risultato.markdown or "") if risultato.success else ""
        testo_parsato = _pulisci_markdown_meteoam(md_grezzo)

    return testo_parsato


async def parse(url: str) -> dict:
    """
    Analizza una pagina www.meteoam.it e restituisce dati strutturati.

    Args:
        url: Un URL da www.meteoam.it.

    Returns:
        dict con chiavi: url, domain, title, html_text, parsed_text.

    Raises:
        ValueError:   Se l'URL non appartiene a meteoam.it.
        RuntimeError: Se la pagina non e' raggiungibile o analizzabile.
    """
    if not _url_appartiene_a_meteoam(url):
        raise ValueError(f"L'URL '{url}' non e' da www.meteoam.it")

    cfg_browser = BrowserConfig(headless=True)

    # Primo crawl per ottenere html_text e titolo
    async with AsyncWebCrawler(config=cfg_browser) as crawler:
        risultato = await crawler.arun(
            url=url,
            config=_crea_config_crawler(_SELETTORE_PRIMARIO_METEOAM),
        )

    if not risultato.success:
        raise RuntimeError(f"Impossibile effettuare il crawl di '{url}': {risultato.error_message}")

    html_text: str = risultato.cleaned_html or risultato.html or ""
    titolo: str = ""
    if risultato.metadata and risultato.metadata.get("title"):
        titolo = risultato.metadata["title"].strip()

    testo_parsato = _pulisci_markdown_meteoam(risultato.markdown or "")

    # Fallback se il selettore primario non ha trovato nulla
    if not testo_parsato:
        async with AsyncWebCrawler(config=cfg_browser) as crawler:
            risultato_fb = await crawler.arun(
                url=url,
                config=_crea_config_crawler(_SELETTORE_FALLBACK_METEOAM),
            )
        if risultato_fb.success:
            testo_parsato = _pulisci_markdown_meteoam(risultato_fb.markdown or "")

    return {
        "url": url,
        "domain": "www.meteoam.it",
        "title": titolo,
        "html_text": html_text,
        "parsed_text": testo_parsato,
    }


async def parse_html(url: str, html_text: str) -> dict:
    """
    Analizza una pagina Meteoam dall'HTML fornito senza scaricare dalla rete.
    Usa il prefisso raw: di Crawl4AI per elaborare la stringa HTML direttamente.

    Args:
        url:       URL originale, usato per i metadati del dominio.
        html_text: Contenuto HTML grezzo della pagina.

    Returns:
        dict con chiavi: url, domain, title, html_text, parsed_text.

    Raises:
        ValueError: Se l'URL non appartiene a meteoam.it.
    """
    if not _url_appartiene_a_meteoam(url):
        raise ValueError(f"L'URL '{url}' non e' da www.meteoam.it")

    testo_parsato = await _crawla_con_fallback(f"raw:{html_text}")

    return {
        "url": url,
        "domain": "www.meteoam.it",
        "title": "",
        "html_text": html_text,
        "parsed_text": testo_parsato,
    }


if __name__ == "__main__":
    risultato = asyncio.run(parse("https://www.meteoam.it/it/previsioni-mensili"))
    print("Titolo:", risultato["title"])
    print(risultato["parsed_text"][:500])
