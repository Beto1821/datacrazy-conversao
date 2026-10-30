"""Transforma os dados brutos da API em métricas de conversão por atendente."""
import pandas as pd

TZ = "America/Sao_Paulo"
SEM_ATENDENTE = "Sem atendente"


def _to_local(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(TZ)


def businesses_df(raw: list[dict]) -> pd.DataFrame:
    cols = ["id", "created_at", "status_at", "status", "total",
            "attendant_id", "atendente", "pipeline", "etapa"]
    if not raw:
        return pd.DataFrame(columns=cols)
    rows = []
    for b in raw:
        att = b.get("attendant") or {}
        stage = b.get("stage") or {}
        rows.append({
            "id": b.get("id"),
            "created_at": b.get("createdAt"),
            "status_at": b.get("statusChangedAt") or b.get("lastMovedAt"),
            "status": b.get("status") or "in_process",
            "total": float(b.get("total") or 0),
            "attendant_id": b.get("attendantId") or att.get("id"),
            "atendente": (att.get("name") or "").strip() or SEM_ATENDENTE,
            "pipeline": (stage.get("pipeline") or {}).get("name") or "-",
            "etapa": stage.get("name") or "-",
        })
    df = pd.DataFrame(rows).drop_duplicates("id")
    df["created_at"] = _to_local(df["created_at"])
    df["status_at"] = _to_local(df["status_at"])
    return df


def leads_df(raw: list[dict]) -> pd.DataFrame:
    cols = ["id", "created_at", "atendente", "origem"]
    if not raw:
        return pd.DataFrame(columns=cols)
    rows = [{
        "id": l.get("id"),
        "created_at": l.get("createdAt"),
        "atendente": ((l.get("attendant") or {}).get("name") or "").strip() or SEM_ATENDENTE,
        "origem": l.get("source") or "Não informada",
    } for l in raw]
    df = pd.DataFrame(rows).drop_duplicates("id")
    df["created_at"] = _to_local(df["created_at"])
    return df


def _safe_div(a, b):
    return (a / b).where(b > 0, 0.0) if isinstance(a, pd.Series) else (a / b if b else 0.0)


def resumo_por_atendente(cohort: pd.DataFrame, vendas: pd.DataFrame, leads: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por atendente.

    cohort: negócios criados no período (entrada).
    vendas: negócios ganhos com data de ganho no período.
    leads:  leads criados no período (atendente atual do lead).
    """
    entrada = cohort.groupby("atendente").agg(
        entradas=("id", "count"),
        ganhos_coorte=("status", lambda s: (s == "won").sum()),
        perdidos_coorte=("status", lambda s: (s == "lost").sum()),
        em_aberto=("status", lambda s: (s == "in_process").sum()),
    )
    fechadas = vendas.groupby("atendente").agg(vendas=("id", "count"), receita=("total", "sum"))
    novos_leads = leads.groupby("atendente").agg(leads=("id", "count"))

    df = entrada.join([fechadas, novos_leads], how="outer").fillna(0)
    int_cols = ["entradas", "ganhos_coorte", "perdidos_coorte", "em_aberto", "vendas", "leads"]
    df[int_cols] = df[int_cols].astype(int)

    df["conv_coorte"] = _safe_div(df["ganhos_coorte"], df["entradas"])
    df["conv_fluxo"] = _safe_div(df["vendas"], df["entradas"])
    df["perda"] = _safe_div(df["perdidos_coorte"], df["entradas"])
    df["ticket_medio"] = _safe_div(df["receita"], df["vendas"])
    return df.reset_index().sort_values(["vendas", "entradas"], ascending=False)


def totais(resumo: pd.DataFrame) -> dict:
    t = resumo[["leads", "entradas", "ganhos_coorte", "perdidos_coorte", "em_aberto",
                "vendas", "receita"]].sum()
    return {
        **t.to_dict(),
        "conv_coorte": _safe_div(t["ganhos_coorte"], t["entradas"]),
        "conv_fluxo": _safe_div(t["vendas"], t["entradas"]),
        "perda": _safe_div(t["perdidos_coorte"], t["entradas"]),
        "ticket_medio": _safe_div(t["receita"], t["vendas"]),
    }


def movimento_diario(cohort: pd.DataFrame, vendas: pd.DataFrame, inicio, fim) -> pd.DataFrame:
    """Entradas e vendas por dia, com conversão acumulada no período."""
    dias = pd.date_range(inicio, fim, freq="D").date
    ent = cohort["created_at"].dt.date.value_counts().reindex(dias, fill_value=0)
    ven = vendas["status_at"].dt.date.value_counts().reindex(dias, fill_value=0)
    df = pd.DataFrame({"dia": pd.to_datetime(dias), "entradas": ent.values, "vendas": ven.values})
    df["conv_acumulada"] = _safe_div(df["vendas"].cumsum(), df["entradas"].cumsum())
    return df
