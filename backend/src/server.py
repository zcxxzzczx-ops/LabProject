"""
FastAPI backend per la pipeline di parsing web — versione completa (Progetto Finale).

Endpoint implementati:
  POST /parse                  - parsing di un URL (live o da DB locale)
  GET  /domains                - elenco dei domini supportati
  GET  /gold_standard          - entry GS per uno specifico URL (dal DB)
  GET  /gold_standard_urls     - tutti gli URL del GS per un dominio
  POST /evaluate               - metriche di valutazione (token-level + extra)
  POST /evaluate_judge         - valutazione tramite LLM Judge
  GET  /full_gs_eval           - valutazione aggregata su tutto il GS di un dominio
  POST /add_web_resource       - aggiunge una risorsa web al DB
  POST /add_gold_standard      - aggiunge un entry al GS nel DB
  DELETE /web_resource         - elimina una web_resource (cascade su GS)
  DELETE /gold_standard        - elimina solo l entry GS
  GET  /db_stats               - statistiche aggregate dal DB
  GET  /db_schema              - schema del DB
  GET  /status                 - stato dei componenti del sistema
"""

import os
from typing import Optional

import mariadb
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from parsers import parse as dispatch_parse, parse_html as dispatch_parse_html
from parsers import SUPPORTED_DOMAINS, is_supported, get_domain
from evaluation import evaluate, rimuovi_markdown
from judge import evaluate_with_judge, check_ollama_status
import database as db


app = FastAPI(
    title="Pipeline di Parsing Web - API Progetto Finale",
    description="Pipeline end-to-end per acquisizione, analisi e valutazione di documenti web.",
    version="2.0.0",
)


# --- Modelli input ---

class RichiestaPostParse(BaseModel):
    url: str
    local: Optional[bool] = False

class RichiestaValutazione(BaseModel):
    parsed_text: str
    gold_text: str

class RichiestaAddWebResource(BaseModel):
    url: str
    html_text: str

class RichiestaAddGoldStandard(BaseModel):
    url: str
    gold_text: str

class RichiestaDeleteUrl(BaseModel):
    url: str


# --- Modelli output ---

class DocumentoParsato(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    parsed_text: str

class RispostaDomini(BaseModel):
    domains: list[str]

class EntryGoldStandard(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    gold_text: str

class RispostaGoldStandardUrls(BaseModel):
    gold_standard_urls: list[str]

class MetricheToken(BaseModel):
    precision: float
    recall: float
    f1: float

class MetricheCharJaccard(BaseModel):
    jaccard_similarity: float

class RispostaValutazione(BaseModel):
    token_level_eval: MetricheToken
    char_overlap_eval: MetricheCharJaccard

class RispostaJudge(BaseModel):
    model_name: str
    judge_score: int
    judge_feedback: str

class RispostaFullGsEval(BaseModel):
    token_level_eval: MetricheToken
    judge_score: float
    char_overlap_eval: MetricheCharJaccard

class RispostaStatus(BaseModel):
    backend: str
    database: str
    ollama: str

class RispostaOperazione(BaseModel):
    status: str


# --- Helpers ---

def _verifica_dominio_supportato(url: str) -> str:
    dominio = get_domain(url)
    if not is_supported(url):
        raise HTTPException(
            status_code=400,
            detail=f"Il dominio '{dominio}' non e supportato. Domini supportati: {SUPPORTED_DOMAINS}",
        )
    return dominio

def _verifica_dominio_stringa(domain: str) -> None:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Il dominio '{domain}' non e supportato. Domini supportati: {SUPPORTED_DOMAINS}",
        )


# --- Endpoints ---

@app.post("/parse", response_model=DocumentoParsato)
async def parse_url(body: RichiestaPostParse) -> DocumentoParsato:
    """Parsing di un URL. Con local=True usa HTML dal DB, altrimenti scarica dalla rete."""
    _verifica_dominio_supportato(body.url)
    if body.local:
        risorsa = db.get_web_resource(body.url)
        if risorsa is None:
            raise HTTPException(status_code=404,
                detail=f"URL '{body.url}' non trovato nel database.")
        try:
            risultato = await dispatch_parse_html(body.url, risorsa["html_text"])
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        try:
            risultato = await dispatch_parse(body.url)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DocumentoParsato(**risultato)


@app.get("/domains", response_model=RispostaDomini)
def elenca_domini() -> RispostaDomini:
    """Restituisce l elenco dei domini supportati."""
    return RispostaDomini(domains=SUPPORTED_DOMAINS)


@app.get("/gold_standard", response_model=EntryGoldStandard)
def recupera_gold_standard(
    url: str = Query(..., description="URL di cui recuperare l entry GS")
) -> EntryGoldStandard:
    """Restituisce l entry Gold Standard per uno specifico URL dal DB."""
    entry = db.get_gold_standard(url)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"URL '{url}' non trovato nel Gold Standard.")
    return EntryGoldStandard(**entry)


@app.get("/gold_standard_urls", response_model=RispostaGoldStandardUrls)
def recupera_gold_standard_urls(
    domain: str = Query(..., description="Dominio di cui recuperare gli URL del GS")
) -> RispostaGoldStandardUrls:
    """Restituisce tutti gli URL del Gold Standard per un dominio."""
    _verifica_dominio_stringa(domain)
    urls = db.get_gold_standard_urls_by_domain(domain)
    return RispostaGoldStandardUrls(gold_standard_urls=urls)


@app.post("/evaluate", response_model=RispostaValutazione)
def valuta_testi(body: RichiestaValutazione) -> RispostaValutazione:
    """Calcola le metriche di valutazione tra testo parsato e Gold Standard."""
    metriche = evaluate(body.parsed_text, body.gold_text)
    return RispostaValutazione(
        token_level_eval=MetricheToken(**metriche["token_level_eval"]),
        char_overlap_eval=MetricheCharJaccard(**metriche["char_overlap_eval"]),
    )


@app.post("/evaluate_judge", response_model=RispostaJudge)
def valuta_con_judge(body: RichiestaValutazione) -> RispostaJudge:
    """Valuta la qualita del parsing usando il LLM Judge via Ollama."""
    parsed_clean = rimuovi_markdown(body.parsed_text)
    gold_clean = rimuovi_markdown(body.gold_text)
    risultato = evaluate_with_judge(parsed_clean, gold_clean)
    return RispostaJudge(**risultato)


@app.get("/full_gs_eval", response_model=RispostaFullGsEval)
async def valutazione_gs_completa(
    domain: str = Query(..., description="Dominio da valutare")
) -> RispostaFullGsEval:
    """
    Valutazione aggregata su tutto il GS per un dominio usando HTML statico nel DB.
    Calcola solo metriche quantitative (no LLM Judge) per garantire tempi rapidi.
    Il judge_score viene letto dal DB se disponibile da valutazioni precedenti.
    """
    _verifica_dominio_stringa(domain)
    gs_entries = db.get_full_gold_standard_db(domain)
    if not gs_entries:
        raise HTTPException(status_code=404,
            detail=f"Nessuna entry GS trovata per il dominio '{domain}'.")

    lista_token: list[dict] = []
    lista_char: list[dict] = []

    for entry in gs_entries:
        url = entry["url"]
        gold_text = entry["gold_text"]
        html_text = entry.get("html_text", "")
        dominio_entry = entry.get("domain", domain)

        try:
            parsed = await dispatch_parse_html(url, html_text)
            testo_parsato = parsed["parsed_text"]
        except Exception:
            testo_parsato = ""

        metriche = evaluate(testo_parsato, gold_text)
        lista_token.append(metriche["token_level_eval"])
        lista_char.append(metriche["char_overlap_eval"])

        # Persiste solo le metriche quantitative nel DB
        try:
            db.insert_evaluation(url=url, domain=dominio_entry,
                precision_score=metriche["token_level_eval"]["precision"],
                recall_score=metriche["token_level_eval"]["recall"],
                f1_score=metriche["token_level_eval"]["f1"],
                extra_metrics={"char_overlap_eval": metriche["char_overlap_eval"]})
        except Exception:
            pass

    def _media(lista: list[dict], chiave: str) -> float:
        return round(sum(d[chiave] for d in lista) / len(lista), 4)

    # Judge score: usa la media dal DB se disponibile, altrimenti 0.0
    avg_judge = db.get_avg_judge_score_by_domain()
    judge_score = avg_judge.get(domain, {}).get("judge_score") or 0.0

    return RispostaFullGsEval(
        token_level_eval=MetricheToken(
            precision=_media(lista_token, "precision"),
            recall=_media(lista_token, "recall"),
            f1=_media(lista_token, "f1"),
        ),
        judge_score=float(judge_score),
        char_overlap_eval=MetricheCharJaccard(
            jaccard_similarity=_media(lista_char, "jaccard_similarity"),
        ),
    )


@app.post("/add_web_resource", response_model=RispostaOperazione)
def aggiungi_web_resource(body: RichiestaAddWebResource) -> RispostaOperazione:
    """Aggiunge o aggiorna una risorsa web nel DB."""
    dominio = get_domain(body.url)
    try:
        db.insert_web_resource(url=body.url, domain=dominio, title="", html_text=body.html_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore DB: {exc}") from exc
    return RispostaOperazione(status="ok")


@app.post("/add_gold_standard", response_model=RispostaOperazione)
def aggiungi_gold_standard(body: RichiestaAddGoldStandard) -> RispostaOperazione:
    """Aggiunge un entry al Gold Standard. La web_resource deve gia esistere."""
    if db.get_web_resource(body.url) is None:
        raise HTTPException(status_code=404,
            detail=f"URL '{body.url}' non presente in web_resources. "
                   "Aggiungere prima con POST /add_web_resource.")
    try:
        db.insert_gold_standard(url=body.url, gold_text=body.gold_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore DB: {exc}") from exc
    return RispostaOperazione(status="ok")


@app.delete("/web_resource", response_model=RispostaOperazione)
def elimina_web_resource(body: RichiestaDeleteUrl) -> RispostaOperazione:
    """Elimina una web_resource e a cascata il gold_standard associato."""
    if not db.delete_web_resource(body.url):
        raise HTTPException(status_code=404,
            detail=f"URL '{body.url}' non trovato in web_resources.")
    return RispostaOperazione(status="ok")


@app.delete("/gold_standard", response_model=RispostaOperazione)
def elimina_gold_standard(body: RichiestaDeleteUrl) -> RispostaOperazione:
    """Elimina solo l entry gold_standard, lasciando intatta la web_resource.Se l entry non esiste restituisce comunque ok (idempotente)."""
    db.delete_gold_standard(body.url)
    return RispostaOperazione(status="ok")


@app.get("/db_stats")
def statistiche_db() -> dict:
    """Statistiche aggregate dal DB: conteggi per dominio e metriche medie."""
    conteggi_wr = db.count_web_resources_by_domain()
    conteggi_gs = db.count_gold_standard_by_domain()
    avg_eval = db.get_avg_evaluation_by_domain()
    avg_judge = db.get_avg_judge_score_by_domain()

    # Garantisce che avg_eval contenga almeno i domini presenti in gold_standard
    # con metriche a zero se non ci sono ancora valutazioni calcolate
    for dominio in conteggi_gs:
        if dominio not in avg_eval:
            avg_eval[dominio] = {
                "token_level_eval": {
                    "precision": 0.0,
                    "recall": 0.0,
                    "f1": 0.0,
                }
            }

    avg_eval_judge: dict = {}
    for dominio in set(list(avg_eval.keys()) + list(avg_judge.keys())):
        avg_eval_judge[dominio] = avg_judge.get(dominio, {"judge_score": None})

    return {
        "web_resources": conteggi_wr,
        "gold_standard": conteggi_gs,
        "avg_eval": avg_eval,
        "avg_eval_judge": avg_eval_judge,
    }


@app.get("/db_schema")
def schema_db() -> dict:
    """Restituisce lo schema del DB con tabelle, colonne, PK e FK."""
    try:
        return db.get_db_schema()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore lettura schema: {exc}") from exc


@app.get("/status", response_model=RispostaStatus)
def stato_sistema() -> RispostaStatus:
    """Verifica lo stato dei componenti. Restituisce sempre HTTP 200."""
    stato_db = "ok"
    try:
        conn = db.get_connection()
        conn.close()
    except Exception:
        stato_db = "error"

    stato_ollama = "ok" if check_ollama_status() else "error"

    return RispostaStatus(backend="ok", database=stato_db, ollama=stato_ollama)
