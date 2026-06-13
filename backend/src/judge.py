"""
Modulo LLM Judge: usa un modello locale via Ollama per valutare la qualità
del testo estratto dai parser confrontandolo con il Gold Standard.

Il modello è configurabile tramite variabile d'ambiente OLLAMA_MODEL.
Il testo in input viene troncato per evitare context window troppo grandi
e tempi di risposta eccessivi su CPU (comportamento consentito dalla specifica).
"""

import json
import os
import re

import httpx


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# Numero massimo di caratteri inviati al modello per ogni testo (troncamento consentito)
_MAX_CHARS: int = 2000

# Timeout generoso per risposta LLM su CPU
_TIMEOUT_SECONDI: float = 120.0


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE: str = """\
Sei un valutatore esperto di qualità del testo estratto da pagine web.
Il tuo compito è confrontare il testo estratto automaticamente da un parser
con il testo di riferimento (Gold Standard) e dare un giudizio.

Testo estratto dal parser:
{parsed_text}

Testo di riferimento (Gold Standard):
{gold_text}

Valuta la qualità del testo estratto considerando:
- Quanto testo rilevante è stato catturato
- Quanto rumore (boilerplate, menu, pubblicità) è presente
- Se il testo è troncato o incompleto

Rispondi SOLO con un oggetto JSON valido nel seguente formato, senza testo aggiuntivo:
{{
  "score": <intero da 1 a 5>,
  "feedback": "<breve descrizione della qualità, max 150 parole>"
}}

Dove 1 = pessimo, 5 = ottimo."""


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def _tronca(testo: str, max_chars: int = _MAX_CHARS) -> str:
    """Tronca il testo al numero massimo di caratteri consentito."""
    if len(testo) <= max_chars:
        return testo
    return testo[:max_chars] + "\n[... troncato ...]"


def _estrai_json(testo_risposta: str) -> dict:
    """
    Tenta di estrarre un oggetto JSON dalla risposta del modello.
    Gestisce il caso in cui il modello aggiunga testo prima/dopo il JSON.
    """
    # Cerca il primo blocco {...}
    match = re.search(r"\{[^{}]*\}", testo_risposta, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: prova a parsare direttamente
    try:
        return json.loads(testo_risposta.strip())
    except json.JSONDecodeError:
        return {}


def _fallback_response(motivo: str) -> dict:
    """Risposta di fallback quando il modello non risponde nel formato atteso."""
    return {
        "model_name": OLLAMA_MODEL,
        "judge_score": 1,
        "judge_feedback": f"Valutazione non disponibile: {motivo}",
    }


def evaluate_with_judge(parsed_text: str, gold_text: str) -> dict:
    """
    Invia parsed_text e gold_text al modello Ollama e restituisce la valutazione.

    Args:
        parsed_text: Testo prodotto dal parser (Markdown rimosso prima di chiamare).
        gold_text:   Testo di riferimento dal Gold Standard.

    Returns:
        Dict con campi obbligatori: model_name (str), judge_score (int 1-5),
        judge_feedback (str).
    """
    prompt = _PROMPT_TEMPLATE.format(
        parsed_text=_tronca(parsed_text),
        gold_text=_tronca(gold_text),
    )

    payload: dict = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,   # bassa temperatura per risposte più deterministiche
            "num_predict": 256,   # limita i token generati per velocità
        },
    }

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDI) as client:
            response = client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        return _fallback_response("timeout nella chiamata a Ollama")
    except httpx.HTTPError as exc:
        return _fallback_response(f"errore HTTP Ollama: {exc}")
    except Exception as exc:
        return _fallback_response(f"errore imprevisto: {exc}")

    testo_generato: str = data.get("response", "")
    giudizio = _estrai_json(testo_generato)

    # Validazione e normalizzazione del risultato
    score = giudizio.get("score")
    feedback = giudizio.get("feedback", "")

    if not isinstance(score, int) or not (1 <= score <= 5):
        # Prova a convertire da float o stringa
        try:
            score = max(1, min(5, int(float(str(score)))))
        except (TypeError, ValueError):
            return _fallback_response(
                f"il modello non ha restituito uno score valido. Risposta grezza: {testo_generato[:200]}"
            )

    if not isinstance(feedback, str) or not feedback.strip():
        feedback = "Nessun feedback testuale fornito dal modello."

    return {
        "model_name": OLLAMA_MODEL,
        "judge_score": score,
        "judge_feedback": feedback.strip(),
    }


def check_ollama_status() -> bool:
    """
    Verifica che Ollama sia raggiungibile e risponda.
    Restituisce True se ok, False altrimenti.
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False
