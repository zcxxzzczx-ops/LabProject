"""
Parser per editorial.rottentomatoes.com (articoli editoriali di Rotten Tomatoes).
Estrae titolo e corpo degli articoli da pagine editoriali/news.
"""

import re
import asyncio
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup


# Punta all'area principale del contenuto dell'articolo
_SELETTORE_CSS_RT = "div.content-body, .editorial-content, .article-body, article"

_TAG_ESCLUSI_RT = [
    "nav", "footer", "header", "script", "style", "noscript",
    ".advertisement", ".ad-container", ".promo-unit",
    ".sidebar", ".social-share", ".tags-list",
    ".newsletter-signup", "#cookie-banner", ".cookie-modal",
    ".author-bio", ".comments-section",
    "cookie-manager", "device-inspection-manager", "mobile-android-banner",
    ".jetpack-instant-search__widget-area",
]

def _url_appartiene_a_rottentomatoes(url: str) -> bool:
    """Restituisce True se l'URL appartiene a editorial.rottentomatoes.com."""
    return urlparse(url).netloc == "editorial.rottentomatoes.com"


def _pulisci_markdown_rt(md_grezzo: str) -> str:
    """Pulisce il Markdown grezzo dalle pagine editoriali di Rotten Tomatoes."""
    testo = re.sub(r"(?i)^(share|tweet|facebook|instagram|pinterest|copy link).*$", "", md_grezzo, flags=re.MULTILINE)
    testo = re.sub(r"!\[.*?\]\(.*?\)", "", testo)
    testo = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", testo)
    righe = testo.splitlines()
    righe_pulite = [ln for ln in righe if len(ln.strip()) >= 3 or ln.strip() == ""]
    testo = "\n".join(righe_pulite)
    testo = re.sub(r"\n{3,}", "\n\n", testo)

    # Tronca a 2000 parole prima del return
    parole = testo.split()
    if len(parole) > 2000:
        testo = ' '.join(parole[:2000])

    return testo.strip()


def _estrai_con_bs4_rt(html_text: str) -> str:
    """
    Estrattore BS4 deterministico per Rotten Tomatoes.
    Antepone il titolo principale come ## heading (markdown), poi testo plain.
    Tronca a 2000 parole totali.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header",
                     "ins", "aside"]):
        tag.decompose()
    radice = (soup.select_one("div.content-body") or
              soup.select_one(".editorial-content") or
              soup.select_one(".article-body") or
              soup.select_one("article") or
              soup.body or soup)

    # Titolo principale come heading markdown
    title_tag = soup.select_one("h1.article-title, h1.entry-title, h1")
    title_md = ""
    if title_tag:
        title_md = "## " + title_tag.get_text(strip=True) + "\n\n"

    testo = radice.get_text(separator=" ", strip=True)
    testo = re.sub(r"\s+", " ", testo).strip()
    parole = (title_md + testo).split()
    if len(parole) > 2000:
        testo = " ".join(parole[:2000])
    else:
        testo = title_md + testo
    return testo.strip()


def _crea_config_crawler() -> CrawlerRunConfig:
    """Costruisce la CrawlerRunConfig condivisa per le pagine Rotten Tomatoes."""
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        css_selector=_SELETTORE_CSS_RT,
        excluded_tags=_TAG_ESCLUSI_RT,
        remove_overlay_elements=True,
        wait_until="networkidle",
        word_count_threshold=5,
    )


async def parse(url: str) -> dict:
    """
    Analizza una pagina editorial.rottentomatoes.com e restituisce dati strutturati.

    Args:
        url: Un URL da editorial.rottentomatoes.com.

    Returns:
        dict con chiavi: url, domain, title, html_text, parsed_text.

    Raises:
        ValueError:   Se l'URL non e' da editorial.rottentomatoes.com.
        RuntimeError: Se la pagina non puo' essere analizzata.
    """
    if not _url_appartiene_a_rottentomatoes(url):
        raise ValueError(f"L'URL '{url}' non e' da editorial.rottentomatoes.com")

    cfg_browser = BrowserConfig(headless=True)
    cfg_crawler = _crea_config_crawler()

    async with AsyncWebCrawler(config=cfg_browser) as crawler:
        risultato = await crawler.arun(url=url, config=cfg_crawler)

    if not risultato.success:
        raise RuntimeError(f"Impossibile effettuare il crawl di '{url}': {risultato.error_message}")

    html_text: str = risultato.cleaned_html or risultato.html or ""
    md_grezzo: str = risultato.markdown or ""

    titolo: str = ""
    if risultato.metadata and risultato.metadata.get("title"):
        titolo = re.sub(r"\s*[|\-\u2013]\s*Rotten Tomatoes.*$", "", risultato.metadata["title"]).strip()

    testo_parsato: str = _pulisci_markdown_rt(md_grezzo)

    return {
        "url": url,
        "domain": "editorial.rottentomatoes.com",
        "title": titolo,
        "html_text": html_text,
        "parsed_text": testo_parsato,
    }


async def parse_html(url: str, html_text: str) -> dict:
    """
    Analizza una pagina Rotten Tomatoes dall'HTML fornito senza scaricare dalla rete.
    Usa il prefisso raw: di Crawl4AI per elaborare la stringa HTML direttamente.

    Args:
        url:       URL originale, usato per i metadati del dominio.
        html_text: Contenuto HTML grezzo della pagina.

    Returns:
        dict con chiavi: url, domain, title, html_text, parsed_text.

    Raises:
        ValueError: Se l'URL non e' da editorial.rottentomatoes.com.
    """
    if not _url_appartiene_a_rottentomatoes(url):
        raise ValueError(f"L'URL '{url}' non e' da editorial.rottentomatoes.com")

    # Estrae il titolo dall'HTML
    titolo: str = ""
    try:
        _soup = BeautifulSoup(html_text, "html.parser")
        _tag_titolo = _soup.find("title")
        if _tag_titolo and _tag_titolo.string:
            titolo = re.sub(r"\s*[|\-\u2013]\s*Rotten Tomatoes.*$", "", _tag_titolo.string).strip()
    except Exception:
        pass

    # BS4 deterministico: più affidabile di crawl4ai raw: su questi HTML
    testo_parsato = _estrai_con_bs4_rt(html_text)

    return {
        "url": url,
        "domain": "editorial.rottentomatoes.com",
        "title": titolo,
        "html_text": html_text,
        "parsed_text": testo_parsato,
    }


if __name__ == "__main__":
    risultato = asyncio.run(parse("https://editorial.rottentomatoes.com/article/best-movies-of-2024/"))
    print("Titolo:", risultato["title"])
    print(risultato["parsed_text"][:500])
