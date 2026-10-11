from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .postgres_service import fetch_all, fetch_one

IDENT = re.compile(r"[^a-zA-Z0-9_]+")
MUTATING_SQL = re.compile(r"^\s*(insert|update|delete|merge|create|alter|drop|truncate|vacuum|analyze|grant|revoke|copy|call|do)\b", re.I)

@dataclass
class Recommendation:
    kind: str
    severity: str
    title: str
    detail: str
    sql: str | None
    confidence: float
    evidence: dict[str, Any]


def safe_ident_part(value: str) -> str:
    value = IDENT.sub("_", value.strip())[:40].strip("_")
    return value.lower() or "idx"


def quote_ident_name(name: str) -> str:
    parts = [p for p in name.split(".") if p]
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts)


def quote_index_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def index_name(table: str, cols: list[str]) -> str:
    digest = hashlib.sha1((table + ":" + ",".join(cols)).encode()).hexdigest()[:8]
    return f"idx_dta_{safe_ident_part(table.split('.')[-1])}_{safe_ident_part('_'.join(cols))}_{digest}"


def create_index_sql(table: str, cols: list[str]) -> str:
    name = index_name(table, cols)
    quoted_cols = ", ".join(quote_ident_name(c) for c in cols)
    return f"CREATE INDEX CONCURRENTLY {quote_index_name(name)} ON {quote_ident_name(table)} ({quoted_cols});"


def normalize_query(query: str) -> str:
    q = re.sub(r"'([^']|'')*'", "?", query)
    q = re.sub(r"\b\d+(?:\.\d+)?\b", "?", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q[:1000]


def extract_candidates_from_query(query: str) -> list[tuple[str, list[str]]]:
    """Heurística conservadora: detecta tabela e colunas simples em WHERE/JOIN/ORDER BY."""
    q = re.sub(r"\s+", " ", query, flags=re.I)
    tables = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][\w\.]*)(?:\s+(?:as\s+)?([a-zA-Z_][\w]*))?", q, flags=re.I)
    alias_to_table: dict[str, str] = {}
    reserved = {"on", "where", "join", "left", "right", "inner", "outer", "cross", "full", "group", "order", "limit", "using"}
    for table, alias in tables:
        alias_to_table[table.split('.')[-1]] = table
        if alias and alias.lower() not in reserved:
            alias_to_table[alias] = table

    pairs: dict[str, list[str]] = {}
    # alias.col em predicados e joins.
    for alias, col in re.findall(r"\b([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*(?:=|>|<|>=|<=|in\b|like\b|ilike\b|between\b|is\b)", q, flags=re.I):
        table = alias_to_table.get(alias)
        if table:
            pairs.setdefault(table, [])
            if col not in pairs[table]:
                pairs[table].append(col)

    # alias.col no outro lado de join: a.id = b.a_id
    for left_alias, left_col, right_alias, right_col in re.findall(r"\b([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*=\s*([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)", q, flags=re.I):
        for alias, col in [(left_alias, left_col), (right_alias, right_col)]:
            table = alias_to_table.get(alias)
            if table:
                pairs.setdefault(table, [])
                if col not in pairs[table]:
                    pairs[table].append(col)

    # Query de uma tabela só com colunas não qualificadas.
    if len(set(alias_to_table.values())) == 1:
        table = next(iter(set(alias_to_table.values())))
        where = re.search(r"\bwhere\b(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)", q, flags=re.I)
        if where:
            for col in re.findall(r"\b([a-zA-Z_][\w]*)\s*(?:=|>|<|>=|<=|in\b|like\b|ilike\b|between\b|is\b)", where.group(1), flags=re.I):
                if col.lower() not in {"and", "or", "not", "is", "null", "true", "false"}:
                    pairs.setdefault(table, [])
                    if col not in pairs[table]:
                        pairs[table].append(col)

    return [(t, cols[:4]) for t, cols in pairs.items() if cols]


def _filter_columns(filter_text: str | None) -> list[str]:
    if not filter_text:
        return []
    cols: list[str] = []
    for col in re.findall(r"\b([a-zA-Z_][\w]*)\b\s*(?:=|>|<|>=|<=|~~|~~\*|!~~|!~~\*|LIKE|ILIKE|IS)", filter_text, flags=re.I):
        if col.lower() not in {"and", "or", "not", "null", "true", "false"} and col not in cols:
            cols.append(col)
    return cols[:4]


async def connection_info(database: str | None = None) -> dict[str, Any]:
    try:
        row = await fetch_one(
            """
            SELECT
                version() AS version,
                current_database() AS database,
                current_user AS username,
                inet_server_addr()::text AS server_addr,
                inet_server_port() AS server_port
            """,
            database=database,
        )
        return {"ok": True, "info": row}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def get_optional_workload(limit: int = 20, database: str | None = None) -> tuple[list[dict], str | None]:
    try:
        rows = await fetch_all(
            """
            SELECT
                queryid::text,
                calls,
                round(total_exec_time::numeric, 2) AS total_exec_time_ms,
                round(mean_exec_time::numeric, 2) AS mean_exec_time_ms,
                rows,
                shared_blks_hit,
                shared_blks_read,
                temp_blks_read,
                temp_blks_written,
                query
            FROM pg_stat_statements
            WHERE query NOT ILIKE 'EXPLAIN%%'
              AND query NOT ILIKE '%%pg_stat_statements%%'
            ORDER BY total_exec_time DESC
            LIMIT %s
            """,
            (limit,),
            database=database,
        )
        return rows, None
    except Exception as exc:
        return [], str(exc)


async def get_catalog_snapshot(database: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["database"] = await fetch_one(
        """
        SELECT
            current_database() AS database,
            pg_size_pretty(pg_database_size(current_database())) AS size_pretty,
            pg_database_size(current_database()) AS size_bytes
        """,
        database=database,
    )
    data["largest_tables"] = await fetch_all(
        """
        SELECT
            n.nspname AS schema_name,
            c.relname AS table_name,
            pg_total_relation_size(c.oid) AS total_bytes,
            pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
            COALESCE(s.seq_scan, 0) AS seq_scan,
            COALESCE(s.idx_scan, 0) AS idx_scan,
            COALESCE(s.n_live_tup, c.reltuples::bigint) AS estimated_rows,
            s.last_analyze,
            s.last_autoanalyze,
            COALESCE(s.n_mod_since_analyze, 0) AS n_mod_since_analyze
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT 20
        """,
        database=database,
    )
    return data


async def resolve_table(table: str, database: str | None = None) -> dict[str, Any] | None:
    if "." in table:
        schema, rel = table.split(".", 1)
        params = (schema.strip('"'), rel.strip('"'))
        where = "n.nspname = %s AND c.relname = %s"
    else:
        params = (table.strip('"'),)
        where = "c.relname = %s AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
    rows = await fetch_all(
        f"""
        SELECT
            c.oid::text AS table_oid,
            n.nspname AS schema_name,
            c.relname AS table_name,
            pg_total_relation_size(c.oid) AS total_bytes,
            pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
            COALESCE(s.n_live_tup, c.reltuples::bigint) AS estimated_rows,
            COALESCE(s.seq_scan, 0) AS seq_scan,
            COALESCE(s.idx_scan, 0) AS idx_scan,
            COALESCE(s.n_mod_since_analyze, 0) AS n_mod_since_analyze,
            s.last_analyze,
            s.last_autoanalyze
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE {where}
          AND c.relkind IN ('r', 'p')
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT 1
        """,
        params,
        database=database,
    )
    return rows[0] if rows else None


async def table_columns(schema: str, table: str, database: str | None = None) -> list[str]:
    rows = await fetch_all(
        """
        SELECT a.attname
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
        database=database,
    )
    return [r["attname"] for r in rows]


async def existing_indexes(schema: str, table: str, database: str | None = None) -> list[dict[str, Any]]:
    return await fetch_all(
        """
        SELECT
            i.indexrelid::regclass::text AS index_name,
            i.indisunique AS is_unique,
            i.indisprimary AS is_primary,
            pg_get_indexdef(i.indexrelid) AS indexdef,
            array_agg(a.attname ORDER BY u.ord) FILTER (WHERE a.attname IS NOT NULL) AS columns
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        LEFT JOIN unnest(i.indkey) WITH ORDINALITY AS u(attnum, ord) ON true
        LEFT JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = u.attnum
        WHERE n.nspname = %s
          AND t.relname = %s
        GROUP BY i.indexrelid, i.indisunique, i.indisprimary
        ORDER BY i.indisprimary DESC, i.indisunique DESC, i.indexrelid::regclass::text
        """,
        (schema, table),
        database=database,
    )


async def column_stats(schema: str, table: str, cols: list[str], database: str | None = None) -> list[dict[str, Any]]:
    if not cols:
        return []
    return await fetch_all(
        """
        SELECT
            attname,
            null_frac,
            n_distinct,
            correlation,
            array_length(most_common_vals, 1) AS mcv_count
        FROM pg_stats
        WHERE schemaname = %s
          AND tablename = %s
          AND attname = ANY(%s)
        ORDER BY array_position(%s, attname)
        """,
        (schema, table, cols, cols),
        database=database,
    )


def _index_cols(idx: dict[str, Any]) -> list[str]:
    return [str(c) for c in (idx.get("columns") or []) if c is not None]


def compare_suggested_index(indexes: list[dict[str, Any]], cols: list[str]) -> dict[str, Any]:
    """Compara um índice candidato com índices reais da tabela.

    A comparação é conservadora: só trata como coberto quando as colunas existentes
    aparecem como prefixo na mesma ordem. Índices parciais, funcionais ou com INCLUDE
    precisam de validação manual via EXPLAIN.
    """
    target = [c.lower() for c in cols]
    if not target:
        return {"status": "invalid", "decision": "skip", "reason": "sem colunas candidatas", "matches": []}

    matches: list[dict[str, Any]] = []
    exact = None
    covering = None
    candidate_extends_existing = None
    same_columns_different_order = None
    same_first_column = None

    for idx in indexes:
        raw_cols = _index_cols(idx)
        idx_cols = [c.lower() for c in raw_cols]
        if not idx_cols:
            continue
        item = {
            "index_name": idx.get("index_name"),
            "index_columns": raw_cols,
            "is_primary": idx.get("is_primary"),
            "is_unique": idx.get("is_unique"),
            "indexdef": idx.get("indexdef"),
        }

        if idx_cols == target:
            item["match_type"] = "exact"
            exact = item
        elif len(idx_cols) > len(target) and idx_cols[:len(target)] == target:
            item["match_type"] = "existing_covers_candidate_prefix"
            covering = covering or item
        elif len(idx_cols) < len(target) and target[:len(idx_cols)] == idx_cols:
            item["match_type"] = "candidate_extends_existing_prefix"
            candidate_extends_existing = candidate_extends_existing or item
        elif set(idx_cols) == set(target):
            item["match_type"] = "same_columns_different_order"
            same_columns_different_order = same_columns_different_order or item
        elif idx_cols and target and idx_cols[0] == target[0]:
            item["match_type"] = "same_leading_column_partial"
            same_first_column = same_first_column or item
        elif set(target).issubset(set(idx_cols)):
            item["match_type"] = "contains_columns_not_as_prefix"
        else:
            continue
        matches.append(item)

    if exact:
        return {
            "status": "redundant_exact",
            "decision": "skip",
            "reason": "já existe índice com exatamente as mesmas colunas na mesma ordem",
            "best_match": exact,
            "matches": matches,
        }
    if covering:
        return {
            "status": "redundant_covered",
            "decision": "skip",
            "reason": "já existe índice cujo prefixo cobre a sugestão",
            "best_match": covering,
            "matches": matches,
        }
    if candidate_extends_existing:
        return {
            "status": "candidate_extends_existing",
            "decision": "review",
            "reason": "existe índice com prefixo igual; novo índice só é justificável se as colunas adicionais filtrarem, ordenarem ou evitarem heap fetch",
            "best_match": candidate_extends_existing,
            "matches": matches,
        }
    if same_columns_different_order:
        return {
            "status": "same_columns_different_order",
            "decision": "review",
            "reason": "já existe índice com as mesmas colunas em outra ordem; validade depende da ordem dos predicados, joins e ORDER BY",
            "best_match": same_columns_different_order,
            "matches": matches,
        }
    if same_first_column:
        return {
            "status": "partial_overlap",
            "decision": "review",
            "reason": "existe índice com a mesma primeira coluna, mas não cobre totalmente a sugestão",
            "best_match": same_first_column,
            "matches": matches,
        }
    return {
        "status": "no_overlap",
        "decision": "create_candidate",
        "reason": "nenhum índice existente cobre a sugestão como prefixo",
        "matches": matches,
    }


async def build_index_recommendation(
    table: str,
    cols: list[str],
    database: str | None = None,
    source: str = "query",
    base_evidence: dict[str, Any] | None = None,
    weight_ms: float | None = None,
) -> Recommendation:
    resolved = await resolve_table(table, database=database)
    if not resolved:
        return Recommendation(
            kind="index",
            severity="low",
            title=f"Candidato não validado: {table} ({', '.join(cols)})",
            detail="A query sugere este índice, mas a tabela não foi localizada no banco selecionado. Verifique schema/search_path.",
            sql=create_index_sql(table, cols) if cols else None,
            confidence=0.25,
            evidence={"table": table, "columns": cols, "reason": "table_not_found", **(base_evidence or {})},
        )

    schema = resolved["schema_name"]
    rel = resolved["table_name"]
    full_table = f"{schema}.{rel}"
    valid_columns = await table_columns(schema, rel, database=database)
    clean_cols = [c for c in cols if c in valid_columns]
    missing_cols = [c for c in cols if c not in valid_columns]
    indexes = await existing_indexes(schema, rel, database=database)
    stats = await column_stats(schema, rel, clean_cols, database=database)
    index_comparison = compare_suggested_index(indexes, clean_cols) if clean_cols else {"status": "invalid", "decision": "skip", "reason": "sem colunas validadas", "matches": []}

    evidence = {
        "database": database,
        "table": resolved,
        "columns_detected": cols,
        "columns_validated": clean_cols,
        "missing_columns": missing_cols,
        "index_comparison": index_comparison,
        "existing_indexes": indexes,
        "column_stats": stats,
        "source": source,
        **(base_evidence or {}),
    }

    if not clean_cols:
        return Recommendation(
            kind="index",
            severity="low",
            title=f"Candidato não validado em {full_table}",
            detail="A tabela existe, mas as colunas detectadas não foram encontradas. A recomendação foi rebaixada.",
            sql=None,
            confidence=0.2,
            evidence=evidence,
        )

    comparison_status = index_comparison.get("status")
    comparison_decision = index_comparison.get("decision")
    best_match = index_comparison.get("best_match") or {}
    if comparison_decision == "skip":
        idx_name = best_match.get("index_name") or "índice existente"
        return Recommendation(
            kind="index-comparison",
            severity="low",
            title=f"Sugestão descartada para {full_table} ({', '.join(clean_cols)})",
            detail=(
                f"Comparação com índices existentes: {index_comparison.get('reason')}. "
                f"Melhor correspondência: {idx_name}. Não criar novo índice; valide por EXPLAIN se o otimizador não estiver usando o índice existente."
            ),
            sql=None,
            confidence=0.9 if comparison_status == "redundant_exact" else 0.84,
            evidence=evidence,
        )

    total_bytes = int(resolved.get("total_bytes") or 0)
    estimated_rows = int(resolved.get("estimated_rows") or 0)
    seq_scan = int(resolved.get("seq_scan") or 0)
    idx_scan = int(resolved.get("idx_scan") or 0)
    n_mod_since_analyze = int(resolved.get("n_mod_since_analyze") or 0)

    confidence = 0.55
    severity = "medium"
    reasons = [f"tabela {full_table}: {resolved.get('total_size')}, ~{estimated_rows:,} linhas".replace(",", ".")]

    if comparison_decision == "review":
        confidence -= 0.12
        reasons.append(f"comparação com índice existente: {index_comparison.get('reason')}")
        if best_match.get("index_name"):
            reasons.append(f"índice relacionado: {best_match.get('index_name')} ({', '.join(best_match.get('index_columns') or [])})")

    if total_bytes > 1024 * 1024 * 1024 or estimated_rows > 1_000_000:
        confidence += 0.18
        severity = "high"
        reasons.append("volume alto")
    elif total_bytes < 32 * 1024 * 1024 and estimated_rows < 50_000:
        confidence -= 0.18
        severity = "low"
        reasons.append("tabela pequena")

    if seq_scan > max(50, idx_scan * 2):
        confidence += 0.1
        reasons.append(f"seq_scan={seq_scan}, idx_scan={idx_scan}")
    if weight_ms and weight_ms > 30_000:
        confidence += 0.1
        severity = "high"
        reasons.append(f"impacto observado em logs: {round(weight_ms, 2)} ms total")
    if n_mod_since_analyze > max(10000, estimated_rows * 0.2):
        confidence -= 0.07
        reasons.append("estatísticas possivelmente desatualizadas; ANALYZE antes de decidir")

    if stats:
        first = stats[0]
        nd = first.get("n_distinct")
        try:
            nd_f = float(nd)
            if nd_f < 0:  # fração negativa de linhas distintas.
                distinct_est = abs(nd_f) * max(estimated_rows, 1)
            else:
                distinct_est = nd_f
            if distinct_est > 1000:
                confidence += 0.08
                reasons.append(f"coluna inicial com boa cardinalidade estimada: ~{int(distinct_est):,} valores".replace(",", "."))
            elif distinct_est <= 10:
                confidence -= 0.12
                reasons.append("coluna inicial parece ter baixa cardinalidade")
        except Exception:
            pass

    confidence = max(0.2, min(0.95, confidence))
    action = "Criar candidato" if comparison_decision == "create_candidate" else "Revisar antes de criar"
    detail = f"{action}. Recomendação específica do ambiente: " + "; ".join(reasons) + ". Validar com EXPLAIN antes de executar."
    return Recommendation(
        kind="index" if comparison_decision == "create_candidate" else "index-comparison",
        severity=severity,
        title=f"Índice candidato em {full_table} ({', '.join(clean_cols)})",
        detail=detail,
        sql=create_index_sql(full_table, clean_cols),
        confidence=confidence,
        evidence=evidence,
    )


async def catalog_recommendations(database: str | None = None) -> list[Recommendation]:
    recs: list[Recommendation] = []

    fk_rows = await fetch_all(
        """
        WITH fk AS (
            SELECT
                c.oid AS constraint_oid,
                n.nspname AS schema_name,
                t.relname AS table_name,
                c.conname AS constraint_name,
                c.conrelid,
                c.conkey,
                array_agg(a.attname ORDER BY u.ord) AS columns
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = u.attnum
            WHERE c.contype = 'f'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            GROUP BY c.oid, n.nspname, t.relname, c.conname, c.conrelid, c.conkey
        )
        SELECT fk.*
        FROM fk
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_index i
            WHERE i.indrelid = fk.conrelid
              AND (string_to_array(i.indkey::text, ' ')::int2[])[1:array_length(fk.conkey, 1)] = fk.conkey
        )
        ORDER BY schema_name, table_name, constraint_name
        LIMIT 100
        """,
        database=database,
    )
    for r in fk_rows:
        table = f"{r['schema_name']}.{r['table_name']}"
        cols = list(r["columns"])
        recs.append(await build_index_recommendation(table, cols, database=database, source="foreign_key", base_evidence=r))

    stale_rows = await fetch_all(
        """
        SELECT
            schemaname AS schema_name,
            relname AS table_name,
            n_live_tup,
            n_mod_since_analyze,
            last_analyze,
            last_autoanalyze
        FROM pg_stat_user_tables
        WHERE n_live_tup > 10000
          AND (last_analyze IS NULL OR n_mod_since_analyze > GREATEST(10000, n_live_tup * 0.2))
        ORDER BY n_mod_since_analyze DESC
        LIMIT 50
        """,
        database=database,
    )
    for r in stale_rows:
        table = f"{r['schema_name']}.{r['table_name']}"
        recs.append(Recommendation(
            kind="statistics",
            severity="medium",
            title=f"Estatísticas possivelmente desatualizadas: {table}",
            detail="Estimativas ruins de cardinalidade podem levar a planos ruins. Rodar ANALYZE antes de criar índice reduz falso positivo.",
            sql=f"ANALYZE {quote_ident_name(table)};",
            confidence=0.8,
            evidence=r,
        ))

    no_pk_rows = await fetch_all(
        """
        SELECT
            n.nspname AS schema_name,
            c.relname AS table_name,
            pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
            pg_total_relation_size(c.oid) AS total_bytes,
            c.reltuples::bigint AS estimated_rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r'
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND pg_total_relation_size(c.oid) > 10 * 1024 * 1024
          AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary)
        ORDER BY pg_total_relation_size(c.oid) DESC
        LIMIT 50
        """,
        database=database,
    )
    for r in no_pk_rows:
        recs.append(Recommendation(
            kind="modeling",
            severity="medium",
            title=f"Tabela grande sem primary key: {r['schema_name']}.{r['table_name']}",
            detail="Recomendação específica: tabela acima de 10 MB sem PK. Avalie chave técnica/natural antes de replicação lógica, manutenção e joins seletivos.",
            sql=None,
            confidence=0.7,
            evidence=r,
        ))

    seq_rows = await fetch_all(
        """
        SELECT
            schemaname AS schema_name,
            relname AS table_name,
            seq_scan,
            seq_tup_read,
            idx_scan,
            n_live_tup
        FROM pg_stat_user_tables
        WHERE seq_scan > 100
          AND seq_tup_read > 100000
          AND seq_scan > COALESCE(idx_scan, 0) * 2
        ORDER BY seq_tup_read DESC
        LIMIT 50
        """,
        database=database,
    )
    for r in seq_rows:
        recs.append(Recommendation(
            kind="workload-structure",
            severity="low",
            title=f"Muitos sequential scans: {r['schema_name']}.{r['table_name']}",
            detail=f"Ambiente indica seq_scan={r['seq_scan']} e seq_tup_read={r['seq_tup_read']}. Para índice preciso, importe logs ou analise uma query real dessa tabela.",
            sql=None,
            confidence=0.58,
            evidence=r,
        ))

    unused_idx = await fetch_all(
        """
        SELECT
            s.schemaname AS schema_name,
            s.relname AS table_name,
            s.indexrelname AS index_name,
            s.idx_scan,
            pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size,
            pg_relation_size(i.indexrelid) AS index_bytes,
            pg_get_indexdef(i.indexrelid) AS indexdef
        FROM pg_stat_user_indexes s
        JOIN pg_index i ON i.indexrelid = s.indexrelid
        WHERE s.idx_scan = 0
          AND NOT i.indisprimary
          AND NOT i.indisunique
          AND pg_relation_size(i.indexrelid) > 10 * 1024 * 1024
        ORDER BY pg_relation_size(i.indexrelid) DESC
        LIMIT 50
        """,
        database=database,
    )
    for r in unused_idx:
        recs.append(Recommendation(
            kind="index-maintenance",
            severity="low",
            title=f"Índice grande sem uso registrado: {r['schema_name']}.{r['index_name']}",
            detail="Candidato a revisão, não a remoção automática. Confirme janela de estatísticas, jobs mensais e relatórios sazonais antes de dropar.",
            sql=f"-- Revisar antes de executar\nDROP INDEX CONCURRENTLY {quote_ident_name(r['schema_name'] + '.' + r['index_name'])};",
            confidence=0.5,
            evidence=r,
        ))

    recs.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r.severity, 3), -r.confidence))
    return recs


async def explain_json(query: str, analyze: bool = False, database: str | None = None) -> dict | None:
    cleaned = query.strip().rstrip(";")
    if not cleaned:
        raise ValueError("Query vazia.")
    if MUTATING_SQL.match(cleaned):
        raise ValueError("Este advisor aceita apenas SELECT/WITH/SHOW/EXPLAIN para reduzir risco operacional.")
    if analyze and not re.match(r"^\s*(select|with)\b", cleaned, re.I):
        raise ValueError("EXPLAIN ANALYZE só é permitido para SELECT/WITH nesta interface.")
    options = "FORMAT JSON, BUFFERS false"
    if analyze:
        options = "ANALYZE true, BUFFERS true, FORMAT JSON"
    explain_sql = f"EXPLAIN ({options}) " + cleaned
    rows = await fetch_all(explain_sql, database=database)
    if not rows:
        return None
    first_value = next(iter(rows[0].values()))
    return first_value[0] if isinstance(first_value, list) else first_value


def walk_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    def rec(node: dict[str, Any], depth: int = 0) -> None:
        node = dict(node)
        node["Depth"] = depth
        nodes.append(node)
        for child in node.get("Plans", []) or []:
            rec(child, depth + 1)
    if plan and "Plan" in plan:
        rec(plan["Plan"])
    return nodes


async def analyze_plan(plan: dict | None, source_query: str, database: str | None = None) -> list[Recommendation]:
    if not plan:
        return []
    recs: list[Recommendation] = []
    nodes = walk_plan(plan)
    query_candidates = dict(extract_candidates_from_query(source_query))

    for node in nodes:
        node_type = node.get("Node Type", "")
        relation = node.get("Relation Name")
        schema = node.get("Schema")
        table = f"{schema}.{relation}" if schema and relation else relation
        total_cost = float(node.get("Total Cost") or 0)
        plan_rows = int(node.get("Plan Rows") or 0)

        if node_type == "Seq Scan" and table and (total_cost > 1000 or plan_rows > 10000):
            cols = _filter_columns(node.get("Filter"))
            if not cols:
                cols = query_candidates.get(table) or query_candidates.get(relation or "") or []
            if cols:
                recs.append(await build_index_recommendation(
                    table,
                    cols,
                    database=database,
                    source="explain_plan",
                    base_evidence={"node": {k: v for k, v in node.items() if k != "Plans"}},
                ))
            else:
                recs.append(Recommendation(
                    kind="index",
                    severity="medium",
                    title=f"Seq Scan caro em {table}",
                    detail="O plano indica leitura sequencial relevante, mas não foi possível detectar predicado indexável. Verifique filtros, funções e casts na query.",
                    sql=None,
                    confidence=0.42,
                    evidence={"node": {k: v for k, v in node.items() if k != "Plans"}},
                ))

        if node_type == "Sort" and total_cost > 1000:
            recs.append(Recommendation(
                kind="query-plan",
                severity="medium",
                title="Sort relevante no plano",
                detail="Avaliar índice compatível com ORDER BY/GROUP BY ou work_mem para esta operação. A recomendação depende das colunas em Sort Key.",
                sql=None,
                confidence=0.55,
                evidence={"sort_key": node.get("Sort Key"), "cost": total_cost, "plan_rows": plan_rows},
            ))

        if node_type == "Nested Loop" and plan_rows > 10000:
            recs.append(Recommendation(
                kind="query-plan",
                severity="medium",
                title="Nested Loop com muitas linhas estimadas",
                detail="Pode indicar ausência de índice no lado interno do join ou estimativas ruins. Verifique os nós filhos e rode ANALYZE se houver grande divergência.",
                sql=None,
                confidence=0.55,
                evidence={"cost": total_cost, "plan_rows": plan_rows},
            ))

    if not recs:
        for table, cols in extract_candidates_from_query(source_query):
            recs.append(await build_index_recommendation(table, cols, database=database, source="query_parser", base_evidence={"query_sample": source_query[:1000]}))
    recs.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r.severity, 3), -r.confidence))
    return recs


def parse_slow_log(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    pattern = re.compile(r"duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms\s+(?:statement:|execute\s+[^:]+:)\s*(.+?)(?=\n[^\n]*duration:\s*[0-9]|\Z)", re.I | re.S)
    for m in pattern.finditer(text):
        duration_ms = float(m.group(1))
        query = m.group(2).strip()
        if query:
            entries.append({"duration_ms": duration_ms, "query": query})

    if not entries:
        line_pattern = re.compile(r"duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms\s+(.*)", re.I)
        for line in text.splitlines():
            m = line_pattern.search(line)
            if m:
                query = m.group(2).replace("statement:", "", 1).strip()
                entries.append({"duration_ms": float(m.group(1)), "query": query})
    return entries


async def analyze_log_text(text: str, min_ms: float = 0, database: str | None = None) -> dict[str, Any]:
    entries = [e for e in parse_slow_log(text) if e["duration_ms"] >= min_ms]
    grouped: dict[str, dict[str, Any]] = {}
    for e in entries:
        norm = normalize_query(e["query"])
        g = grouped.setdefault(norm, {"normalized_query": norm, "calls": 0, "total_ms": 0.0, "max_ms": 0.0, "sample_query": e["query"]})
        g["calls"] += 1
        g["total_ms"] += e["duration_ms"]
        g["max_ms"] = max(g["max_ms"], e["duration_ms"])

    rows = []
    recs: list[Recommendation] = []
    for g in grouped.values():
        g["mean_ms"] = round(g["total_ms"] / max(g["calls"], 1), 2)
        g["total_ms"] = round(g["total_ms"], 2)
        g["max_ms"] = round(g["max_ms"], 2)
        rows.append(g)
        for table, cols in extract_candidates_from_query(g["sample_query"]):
            recs.append(await build_index_recommendation(
                table,
                cols,
                database=database,
                source="slow_log",
                base_evidence=g,
                weight_ms=float(g["total_ms"]),
            ))
    rows.sort(key=lambda x: x["total_ms"], reverse=True)
    recs.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r.severity, 3), -r.confidence))
    return {"entries": entries, "groups": rows[:100], "recommendations": recs[:100]}


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)
