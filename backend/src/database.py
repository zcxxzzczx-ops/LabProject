"""
Modulo database: gestisce la connessione a MariaDB e tutte le operazioni CRUD
sulle tabelle web_resources e gold_standard (tabelle obbligatorie) più le
tabelle ausiliarie per le valutazioni.

Le credenziali vengono lette da variabili d'ambiente iniettate da Docker Compose.
"""

import json
import os
from contextlib import contextmanager
from typing import Generator

import mariadb


# ---------------------------------------------------------------------------
# Configurazione connessione (da env)
# ---------------------------------------------------------------------------

_DB_CONFIG: dict = {
    "host": os.getenv("DB_HOST", "mariadb"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "labuser"),
    "password": os.getenv("DB_PASSWORD", "labpassword"),
    "database": os.getenv("DB_NAME", "labdb"),
    "autocommit": False,
}


# ---------------------------------------------------------------------------
# Connessione
# ---------------------------------------------------------------------------

def get_connection() -> mariadb.Connection:
    """Apre e restituisce una connessione MariaDB. Il chiamante è responsabile della chiusura."""
    return mariadb.connect(**_DB_CONFIG)


@contextmanager
def db_cursor() -> Generator[tuple[mariadb.Connection, mariadb.Cursor], None, None]:
    """
    Context manager che fornisce (conn, cursor) con commit automatico su successo
    e rollback automatico su eccezione.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Inizializzazione schema
# ---------------------------------------------------------------------------

DDL_STATEMENTS: list[str] = [
    # Tabella obbligatoria: web_resources
    # url usa CHARACTER SET utf8mb3 (3 byte/char): 1024*3 = 3072 byte = limite esatto MariaDB
    """
    CREATE TABLE IF NOT EXISTS web_resources (
        url         VARCHAR(1024) CHARACTER SET utf8mb3 NOT NULL PRIMARY KEY,
        domain      VARCHAR(255)  NOT NULL,
        title       VARCHAR(1024) NOT NULL DEFAULT '',
        html_text   LONGTEXT      NOT NULL,
        created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    # Tabella obbligatoria: gold_standard (FK verso web_resources, CASCADE DELETE)
    """
    CREATE TABLE IF NOT EXISTS gold_standard (
        url         VARCHAR(1024) CHARACTER SET utf8mb3 NOT NULL PRIMARY KEY,
        gold_text   LONGTEXT      NOT NULL,
        created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_gs_web_resource
            FOREIGN KEY (url) REFERENCES web_resources(url)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    # Tabella ausiliaria: valutazioni metriche
    """
    CREATE TABLE IF NOT EXISTS evaluations (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        url             VARCHAR(1024) CHARACTER SET utf8mb3 NOT NULL,
        domain          VARCHAR(255)  NOT NULL,
        precision_score FLOAT         NOT NULL,
        recall_score    FLOAT         NOT NULL,
        f1_score        FLOAT         NOT NULL,
        extra_metrics   JSON,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_eval_web_resource
            FOREIGN KEY (url) REFERENCES web_resources(url)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    # Tabella ausiliaria: giudizi LLM
    """
    CREATE TABLE IF NOT EXISTS llm_judgements (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        url             VARCHAR(1024) CHARACTER SET utf8mb3 NOT NULL,
        domain          VARCHAR(255)  NOT NULL,
        model_name      VARCHAR(255)  NOT NULL,
        judge_score     INT           NOT NULL,
        judge_feedback  TEXT          NOT NULL,
        created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_judge_web_resource
            FOREIGN KEY (url) REFERENCES web_resources(url)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
]


def init_schema() -> None:
    """Crea tutte le tabelle se non esistono già."""
    with db_cursor() as (conn, cur):
        for stmt in DDL_STATEMENTS:
            cur.execute(stmt)


# ---------------------------------------------------------------------------
# web_resources — CRUD
# ---------------------------------------------------------------------------

def insert_web_resource(url: str, domain: str, title: str, html_text: str) -> None:
    """
    Inserisce o aggiorna una riga in web_resources.
    Usa INSERT ... ON DUPLICATE KEY UPDATE per essere idempotente.
    """
    sql = """
        INSERT INTO web_resources (url, domain, title, html_text)
        VALUES (?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            domain    = VALUES(domain),
            title     = VALUES(title),
            html_text = VALUES(html_text)
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (url, domain, title, html_text))


def delete_web_resource(url: str) -> bool:
    """
    Elimina la riga web_resources con l'URL indicato (cascade su gold_standard).
    Restituisce True se una riga è stata eliminata, False se non esisteva.
    """
    with db_cursor() as (conn, cur):
        cur.execute("DELETE FROM web_resources WHERE url = ?", (url,))
        return cur.rowcount > 0


def get_web_resource(url: str) -> dict | None:
    """Restituisce la riga web_resources per l'URL, oppure None se assente."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT url, domain, title, html_text, created_at FROM web_resources WHERE url = ?",
            (url,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "url": row[0], "domain": row[1], "title": row[2],
            "html_text": row[3], "created_at": str(row[4]),
        }


def count_web_resources_by_domain() -> dict[str, int]:
    """Restituisce {dominio: numero_righe} per tutti i domini presenti."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT domain, COUNT(*) FROM web_resources GROUP BY domain"
        )
        return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# gold_standard — CRUD
# ---------------------------------------------------------------------------

def insert_gold_standard(url: str, gold_text: str) -> None:
    """
    Inserisce o aggiorna una riga in gold_standard.
    La web_resource corrispondente deve già esistere.
    """
    sql = """
        INSERT INTO gold_standard (url, gold_text)
        VALUES (?, ?)
        ON DUPLICATE KEY UPDATE gold_text = VALUES(gold_text)
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (url, gold_text))


def delete_gold_standard(url: str) -> bool:
    """
    Elimina solo la riga gold_standard lasciando intatta web_resources.
    Restituisce True se eliminata, False se non esisteva.
    """
    with db_cursor() as (conn, cur):
        cur.execute("DELETE FROM gold_standard WHERE url = ?", (url,))
        return cur.rowcount > 0


def get_gold_standard(url: str) -> dict | None:
    """
    Restituisce l'entry GS completa (join con web_resources) per l'URL, o None.
    """
    sql = """
        SELECT wr.url, wr.domain, wr.title, wr.html_text, gs.gold_text, gs.created_at
        FROM gold_standard gs
        JOIN web_resources wr ON gs.url = wr.url
        WHERE gs.url = ?
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (url,))
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "url": row[0], "domain": row[1], "title": row[2],
            "html_text": row[3], "gold_text": row[4], "created_at": str(row[5]),
        }


def get_gold_standard_urls_by_domain(domain: str) -> list[str]:
    """Restituisce tutti gli URL del GS per un dato dominio."""
    sql = """
        SELECT gs.url
        FROM gold_standard gs
        JOIN web_resources wr ON gs.url = wr.url
        WHERE wr.domain = ?
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (domain,))
        return [row[0] for row in cur.fetchall()]


def get_full_gold_standard_db(domain: str) -> list[dict]:
    """Restituisce tutte le entry GS complete per un dominio."""
    sql = """
        SELECT wr.url, wr.domain, wr.title, wr.html_text, gs.gold_text
        FROM gold_standard gs
        JOIN web_resources wr ON gs.url = wr.url
        WHERE wr.domain = ?
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (domain,))
        rows = cur.fetchall()
        return [
            {"url": r[0], "domain": r[1], "title": r[2], "html_text": r[3], "gold_text": r[4]}
            for r in rows
        ]


def count_gold_standard_by_domain() -> dict[str, int]:
    """Restituisce {dominio: numero_righe} per gold_standard."""
    sql = """
        SELECT wr.domain, COUNT(*)
        FROM gold_standard gs
        JOIN web_resources wr ON gs.url = wr.url
        GROUP BY wr.domain
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql)
        return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# evaluations — insert e aggregazione
# ---------------------------------------------------------------------------

def insert_evaluation(
    url: str,
    domain: str,
    precision_score: float,
    recall_score: float,
    f1_score: float,
    extra_metrics: dict | None = None,
) -> None:
    """Salva il risultato di una valutazione metrica per un URL."""
    sql = """
        INSERT INTO evaluations (url, domain, precision_score, recall_score, f1_score, extra_metrics)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (url, domain, precision_score, recall_score, f1_score,
                          json.dumps(extra_metrics) if extra_metrics else None))


def get_avg_evaluation_by_domain() -> dict[str, dict]:
    """
    Restituisce le metriche medie per dominio calcolate dalle valutazioni salvate.
    Formato: {dominio: {"token_level_eval": {"precision": x, "recall": y, "f1": z}}}
    """
    sql = """
        SELECT domain,
               AVG(precision_score), AVG(recall_score), AVG(f1_score)
        FROM evaluations
        GROUP BY domain
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql)
        result = {}
        for row in cur.fetchall():
            result[row[0]] = {
                "token_level_eval": {
                    "precision": round(row[1], 4),
                    "recall": round(row[2], 4),
                    "f1": round(row[3], 4),
                }
            }
        return result


# ---------------------------------------------------------------------------
# llm_judgements — insert e aggregazione
# ---------------------------------------------------------------------------

def insert_llm_judgement(
    url: str,
    domain: str,
    model_name: str,
    judge_score: int,
    judge_feedback: str,
) -> None:
    """Salva il giudizio LLM per un URL."""
    sql = """
        INSERT INTO llm_judgements (url, domain, model_name, judge_score, judge_feedback)
        VALUES (?, ?, ?, ?, ?)
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql, (url, domain, model_name, judge_score, judge_feedback))


def get_avg_judge_score_by_domain() -> dict[str, dict]:
    """
    Restituisce il judge_score medio per dominio.
    Formato: {dominio: {"judge_score": x}}
    """
    sql = """
        SELECT domain, AVG(judge_score)
        FROM llm_judgements
        GROUP BY domain
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql)
        return {row[0]: {"judge_score": round(row[1], 4)} for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Schema DB (per GET /db_schema)
# ---------------------------------------------------------------------------

def get_db_schema() -> dict:
    """
    Legge dinamicamente lo schema del DB da INFORMATION_SCHEMA e restituisce
    un dict nel formato richiesto dalla specifica.
    """
    sql = """
        SELECT
            c.TABLE_NAME,
            c.COLUMN_NAME,
            c.COLUMN_TYPE,
            c.COLUMN_KEY,
            k.REFERENCED_TABLE_NAME,
            k.REFERENCED_COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
            ON  k.TABLE_SCHEMA   = c.TABLE_SCHEMA
            AND k.TABLE_NAME     = c.TABLE_NAME
            AND k.COLUMN_NAME    = c.COLUMN_NAME
            AND k.REFERENCED_TABLE_NAME IS NOT NULL
        WHERE c.TABLE_SCHEMA = DATABASE()
        ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
    """
    with db_cursor() as (conn, cur):
        cur.execute(sql)
        schema: dict[str, dict] = {}
        for row in cur.fetchall():
            table, col, col_type, col_key, ref_table, ref_col = row
            if table not in schema:
                schema[table] = {}
            desc = col_type
            if col_key == "PRI":
                desc += ", PK"
                if ref_table:
                    desc += f", FK({ref_table}.{ref_col})"
            elif ref_table:
                desc += f", FK({ref_table}.{ref_col})"
            schema[table][col] = desc
        return schema
