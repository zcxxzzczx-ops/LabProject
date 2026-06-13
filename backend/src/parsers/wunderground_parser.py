"""
Parser per www.wunderground.com (Weather Underground).
Estrae dati meteo e testo degli articoli da pagine di stazioni/previsioni.
"""

import re
import json as _json
import html as _html
import asyncio
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


_USER_AGENT_WU = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# headers va in BrowserConfig, NON in CrawlerRunConfig (non supportato in 0.4.247)
_BROWSER_HEADERS_WU = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}


def _url_appartiene_a_wunderground(url: str) -> bool:
    """Restituisce True se l'URL appartiene a www.wunderground.com."""
    return urlparse(url).netloc in ("www.wunderground.com", "wunderground.com")


def _e_pagina_articolo(url: str) -> bool:
    """
    Restituisce True solo se l'URL e' di un articolo/blog (non meteo/hourly/forecast).

    Le pagine non-articolo (es. /hourly/..., /weather/..., /forecast/...) contengono
    nel JSON SSR (app-root-state) anche teaser di articoli correlati con campi
    'title'/'body' validi: se si applicasse l'estrazione articolo anche a queste
    pagine si rischierebbe di estrarre il testo di un articolo non correlato
    invece del contenuto meteo effettivo.
    """
    path = urlparse(url).path
    return bool(re.match(r"^/(article|cat6|blog)/", path))


def _crea_browser_config() -> BrowserConfig:
    """BrowserConfig con user-agent realistico e headers per eludere il bot-detection."""
    return BrowserConfig(
        headless=True,
        user_agent=_USER_AGENT_WU,
        headers=_BROWSER_HEADERS_WU,
        extra_args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )


def _crea_config_crawler() -> CrawlerRunConfig:
    """
    Un unico crawl che include gli script (per estrarre app-root-state negli articoli)
    e attende il caricamento JS. Funziona sia per articoli che per pagine meteo.
    """
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        remove_overlay_elements=True,
        wait_until="networkidle",
        page_timeout=60000,
        delay_before_return_html=4.0,
        word_count_threshold=5,
        simulate_user=True,
        override_navigator=True,
    )


# ── Estrazione articoli dal JSON SSR (app-root-state) ──────────────────────────

def _cerca_articolo_ricorsivo(data: object, depth: int = 0) -> dict | None:
    """
    Cerca ricorsivamente un dict con 'title' e 'body' (body HTML ≥ 200 chars).
    Robusto a variazioni nella struttura del JSON tra versioni del sito.
    """
    if depth > 8:
        return None
    if isinstance(data, dict):
        if (
            "title" in data
            and "body" in data
            and isinstance(data.get("body"), str)
            and len(data["body"]) > 200
        ):
            return data
        for v in data.values():
            result = _cerca_articolo_ricorsivo(v, depth + 1)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _cerca_articolo_ricorsivo(item, depth + 1)
            if result:
                return result
    return None


def _estrai_articolo_da_json(html_text: str) -> str:
    """
    Estrae il corpo dell'articolo dal JSON 'app-root-state' embedded nella pagina.
    Restituisce stringa vuota se non trova dati strutturati.
    """
    match = re.search(
        r'<script[^>]+id=["\']app-root-state["\'][^>]*>(.*?)</script>',
        html_text, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return ""

    try:
        json_str = _html.unescape(match.group(1))
        data = _json.loads(json_str)
    except Exception:
        return ""

    article = _cerca_articolo_ricorsivo(data)
    if not article:
        return ""

    title     = article.get("title", "").strip()
    sub       = article.get("subHeadline", "").strip()
    body_html = article.get("body", "")

    body_soup = BeautifulSoup(body_html, "html.parser")
    for div in body_soup.find_all("div", id=re.compile(r"^wxn")):
        div.decompose()

    parts: list[str] = []
    if title:
        parts.append("## " + title)
    if sub:
        parts.append(sub)
    for p in body_soup.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
        text = re.sub(r"\s+", " ", p.get_text(separator=" ", strip=True)).strip()
        if len(text) >= 15:
            parts.append(text)

    return "\n\n".join(parts)


# ── Estrazione pagine meteo (non articolo) ─────────────────────────────────────

# Frammenti di "boilerplate"/UI da scartare nell'estrazione generica
# (rumore tipico delle pagine meteo: form di segnalazione stazione,
# link di navigazione, controlli mappa, etc.)
_BOILERPLATE_SUBSTR = [
    "report this station", "report station", "bad data", "select the information",
    "no pws", "reset map", "add pws", "showing stations", "showing", "previous day",
    "next day", "current station", "personal weather station", "elevation :",
    "find a station", "view calendar", "top video stories", "see more",
    "star_rate", "date_range", "warning active statement", "( see more )",
]


def _e_boilerplate(testo: str) -> bool:
    """Restituisce True se il testo e' un frammento di UI/boilerplate da scartare."""
    basso = testo.lower()
    return any(b in basso for b in _BOILERPLATE_SUBSTR)


def _estrai_moduli_dati(radice: "BeautifulSoup", visti: set[str]) -> list[str]:
    """
    Estrae i blocchi '.data-module' (es. 'Additional Conditions', 'Astronomy')
    nel formato 'Etichetta Valore' per riga, e rimuove i moduli processati
    dall'albero per non riprocessarli nell'estrazione generica successiva.
    """
    parti: list[str] = []
    for modulo in radice.select(".data-module"):
        header = modulo.select_one(".module-header")
        header_txt = header.get_text(" ", strip=True) if header else ""
        if header_txt and header_txt not in visti:
            parti.append(header_txt)
            visti.add(header_txt)
        for riga in modulo.select(".row"):
            colonne = riga.find_all("div", recursive=False)
            if len(colonne) >= 2:
                etichetta = colonne[0].get_text(" ", strip=True)
                valore = colonne[1].get_text(" ", strip=True)
                linea = f"{etichetta} {valore}".strip()
                if linea and linea not in visti:
                    parti.append(linea)
                    visti.add(linea)
        modulo.decompose()
    return parti


def _estrai_pagina_meteo(html_text: str) -> str:
    """
    Estrae il testo da pagine meteo (hourly, forecast, weather, ...) di
    Weather Underground.

    Gestisce in modo specifico i moduli a blocchi (es. 'Additional Conditions',
    'Astronomy'), che sul DOM sono righe etichetta/valore non catturate bene
    dall'estrazione generica per elementi foglia, poi raccoglie il resto del
    testo sostanziale evitando duplicazioni e rumore di interfaccia (form di
    segnalazione stazione, controlli mappa, link di navigazione, ecc.).
    """
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "ins", "aside"]):
        tag.decompose()

    title_md = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        titolo = re.sub(r"\s*[|\-\u2013]\s*Weather Underground.*$", "", title_tag.string).strip()
        if titolo:
            title_md = "## " + titolo

    radice = soup.select_one("#inner-content") or soup.body or soup

    parts: list[str] = []
    if title_md:
        parts.append(title_md)

    testi_visti: set[str] = set()

    # Moduli a blocchi (Additional Conditions, Astronomy, ...)
    parts.extend(_estrai_moduli_dati(radice, testi_visti))

    # Estrazione generica per elementi foglia con testo sostanziale
    for el in radice.find_all(["p", "h1", "h2", "h3", "h4", "li", "span", "div"]):
        if el.find(["p", "h1", "h2", "h3", "h4", "li", "div"]):
            continue
        testo = re.sub(r"\s+", " ", el.get_text(separator=" ", strip=True)).strip()
        if len(testo) < 4 or testo in testi_visti:
            continue
        if _e_boilerplate(testo):
            continue
        if re.fullmatch(r"[\W_]+", testo):
            continue
        testi_visti.add(testo)
        parts.append(testo)

    if len(parts) > 1:
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts)).strip()

    # Fallback grezzo
    testo = re.sub(r"\s+", " ", radice.get_text(separator=" ", strip=True)).strip()
    return re.sub(r"\n{3,}", "\n\n", (title_md + "\n\n" + testo).strip())


# ── Funzione di parsing unificata ──────────────────────────────────────────────

def _estrai_testo(html_text: str, url: str = "") -> str:
    """
    Prova prima l'estrazione articolo dal JSON SSR (app-root-state),
    ma solo per pagine articolo/blog (vedi _e_pagina_articolo);
    per tutte le altre pagine (meteo, hourly, forecast, ...) usa
    direttamente il parser per pagine meteo standard.
    """
    if _e_pagina_articolo(url):
        testo = _estrai_articolo_da_json(html_text)
        if testo and len(testo) > 300:
            return testo
    return _estrai_pagina_meteo(html_text)


async def parse(url: str) -> dict:
    """
    Analizza una pagina www.wunderground.com e restituisce dati strutturati.

    Esegue un unico crawl con Playwright (script inclusi per SSR),
    poi estrae il testo con _estrai_testo() che gestisce sia articoli
    che pagine meteo stazione/previsioni.

    Args:
        url: URL da www.wunderground.com.

    Returns:
        dict con chiavi: url, domain, title, html_text, parsed_text.

    Raises:
        ValueError:   se l'URL non è di wunderground.com.
        RuntimeError: se il crawl fallisce.
    """
    if not _url_appartiene_a_wunderground(url):
        raise ValueError(f"L'URL '{url}' non è da www.wunderground.com")

    async with AsyncWebCrawler(config=_crea_browser_config()) as crawler:
        risultato = await crawler.arun(url=url, config=_crea_config_crawler())

    if not risultato.success:
        raise RuntimeError(
            f"Impossibile effettuare il crawl di '{url}': {risultato.error_message}"
        )

    html_grezzo: str = risultato.html or ""

    titolo = ""
    if risultato.metadata and risultato.metadata.get("title"):
        titolo = re.sub(
            r"\s*[|\-\u2013]\s*Weather Underground.*$",
            "", risultato.metadata["title"]
        ).strip()

    return {
        "url": url,
        "domain": "www.wunderground.com",
        "title": titolo,
        "html_text": html_grezzo,
        "parsed_text": _estrai_testo(html_grezzo, url),
    }


async def parse_html(url: str, html_text: str) -> dict:
    """
    Analizza una pagina Wunderground dall'HTML fornito (senza rete).
    Usato da POST /parse con local=True.

    Args:
        url:       URL originale (usato solo per i metadati).
        html_text: HTML grezzo della pagina.

    Returns:
        dict con chiavi: url, domain, title, html_text, parsed_text.

    Raises:
        ValueError: se l'URL non è di wunderground.com.
    """
    if not _url_appartiene_a_wunderground(url):
        raise ValueError(f"L'URL '{url}' non è da www.wunderground.com")

    titolo = ""
    soup_t = BeautifulSoup(html_text, "html.parser")
    tag_t  = soup_t.find("title")
    if tag_t and tag_t.string:
        titolo = re.sub(
            r"\s*[|\-\u2013]\s*Weather Underground.*$", "", tag_t.string
        ).strip()

    return {
        "url": url,
        "domain": "www.wunderground.com",
        "title": titolo,
        "html_text": html_text,
        "parsed_text": _estrai_testo(html_text, url),
    }


if __name__ == "__main__":
    # Test rapido su un articolo del gold standard
    url_test = "https://www.wunderground.com/article/news/climate/news/2026-05-11-summer-el-nino-impacts"
    res = asyncio.run(parse(url_test))
    print("Titolo:", res["title"])
    print(res["parsed_text"][:500])