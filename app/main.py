"""Dashboard de conversão por atendente - DataCrazy CRM."""
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datacrazy import DataCrazyClient
from metrics import (SEM_ATENDENTE, TZ, businesses_df, leads_df, movimento_diario,
                     resumo_por_atendente, totais)

# Paleta (categórica validada + cores de status)
AZUL, LARANJA = "#2a78d6", "#eb6834"
GANHO, ABERTO, PERDIDO = "#008300", "#a3a29c", "#e34948"
TEXTO_2 = "#52514e"
GRID = "#e8e7e3"

st.set_page_config(page_title="Conversão por Atendente", page_icon="📈", layout="wide")


def fmt_brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%".replace(".", ",")


def base_layout(fig: go.Figure, height: int = 380, **kw) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=10, r=10, t=30, b=10),
        font=dict(color=TEXTO_2), legend=dict(orientation="h", y=1.08, x=0),
        bargap=0.3, **kw)
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


@st.cache_resource
def get_client() -> DataCrazyClient:
    token = os.getenv("CGAVE_API") or os.getenv("DATACRAZY_TOKEN")
    if not token:
        st.error("Defina a variável CGAVE_API no arquivo .env com a chave da API DataCrazy.")
        st.stop()
    return DataCrazyClient(token.strip().strip('"'))


@st.cache_data(ttl=900, show_spinner=False)
def carregar(inicio: date, fim: date):
    tz = ZoneInfo(TZ)
    start = datetime.combine(inicio, time.min, tz)
    end = datetime.combine(fim, time.max, tz)
    now = datetime.now(tz)
    c = get_client()
    leads = c.leads_created(start, end)
    criados = c.businesses_created(start, end)
    # lastMovedAt >= data do ganho, então buscar movidos de start até agora cobre todos os ganhos do período
    ganhos = c.businesses_won_moved(start, max(end, now))
    return leads, criados, ganhos, now.strftime("%d/%m/%Y %H:%M")


# ---------------- Cabeçalho e filtros ----------------
st.title("Conversão por Atendente")
st.caption("Entrada de leads e negócios × vendas ganhas no CRM DataCrazy")

hoje = datetime.now(ZoneInfo(TZ)).date()
f1, f2, f3 = st.columns([2, 1, 1])
periodo = f1.date_input("Período", value=(hoje.replace(day=1), hoje), max_value=hoje, format="DD/MM/YYYY")
if not isinstance(periodo, tuple) or len(periodo) != 2:
    st.info("Selecione data inicial e final.")
    st.stop()
inicio, fim = periodo
if f3.button("Atualizar dados", use_container_width=True):
    carregar.clear()

with st.spinner("Buscando dados na API DataCrazy (respeitando limite de 60 req/min)..."):
    try:
        raw_leads, raw_criados, raw_ganhos, atualizado = carregar(inicio, fim)
    except Exception as e:  # noqa: BLE001
        st.error(f"Erro ao consultar API: {e}")
        st.stop()

leads = leads_df(raw_leads)
cohort = businesses_df(raw_criados)
ganhos = businesses_df(raw_ganhos)
tz = ZoneInfo(TZ)
ini_dt = pd.Timestamp(datetime.combine(inicio, time.min, tz))
fim_dt = pd.Timestamp(datetime.combine(fim, time.max, tz))
vendas = ganhos[(ganhos["status_at"] >= ini_dt) & (ganhos["status_at"] <= fim_dt)]

pipelines = sorted(set(cohort["pipeline"]) | set(vendas["pipeline"]))
padrao = [p for p in pipelines if p.lower() == "vendas"] or pipelines
sel_pipes = f2.multiselect("Pipeline", pipelines, default=padrao)
cohort = cohort[cohort["pipeline"].isin(sel_pipes)]
vendas = vendas[vendas["pipeline"].isin(sel_pipes)]

atendentes = sorted(set(cohort["atendente"]) | set(vendas["atendente"]) | set(leads["atendente"]))
with st.expander("Filtrar atendentes"):
    sel_att = st.multiselect("Atendentes", atendentes,
                             default=[a for a in atendentes if a != SEM_ATENDENTE])
cohort = cohort[cohort["atendente"].isin(sel_att)]
vendas = vendas[vendas["atendente"].isin(sel_att)]
leads = leads[leads["atendente"].isin(sel_att)]

resumo = resumo_por_atendente(cohort, vendas, leads)
tot = totais(resumo) if not resumo.empty else None
if tot is None:
    st.warning("Sem dados para os filtros selecionados.")
    st.stop()

# ---------------- KPIs gerais ----------------
k = st.columns(7)
k[0].metric("Leads novos atribuídos", f"{int(tot['leads']):,}".replace(",", "."))
k[1].metric("Entradas (negócios)", f"{int(tot['entradas']):,}".replace(",", "."))
k[2].metric("Vendas ganhas", f"{int(tot['vendas']):,}".replace(",", "."))
k[3].metric("Conversão (fluxo)", fmt_pct(tot["conv_fluxo"]), help="Vendas ganhas no período ÷ negócios criados no período")
k[4].metric("Conversão (coorte)", fmt_pct(tot["conv_coorte"]), help="Dos negócios criados no período, % que já estão ganhos")
k[5].metric("Receita", fmt_brl(tot["receita"]))
k[6].metric("Ticket médio", fmt_brl(tot["ticket_medio"]))
st.caption(f"Dados de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} · atualizado {atualizado} · cache 15 min · "
           "pipeline filtra negócios; leads são filtrados só por atendente.")

# ---------------- Por atendente ----------------
st.subheader("Por atendente")
r = resumo[resumo["atendente"] != ""].copy()
c1, c2 = st.columns(2)

ordem = r.sort_values("conv_fluxo")
fig = go.Figure(go.Bar(
    x=ordem["conv_fluxo"], y=ordem["atendente"], orientation="h", marker_color=AZUL,
    marker_cornerradius=4, text=[fmt_pct(v) for v in ordem["conv_fluxo"]], textposition="outside",
    customdata=ordem[["vendas", "entradas"]],
    hovertemplate="<b>%{y}</b><br>Conversão %{text}<br>%{customdata[0]} vendas / %{customdata[1]} entradas<extra></extra>"))
fig.add_vline(x=tot["conv_fluxo"], line_dash="dot", line_color=TEXTO_2,
              annotation_text=f"Geral {fmt_pct(tot['conv_fluxo'])}", annotation_position="top")
base_layout(fig, height=max(320, 34 * len(ordem)), title="Taxa de conversão (fluxo)")
fig.update_xaxes(tickformat=".0%")
c1.plotly_chart(fig, use_container_width=True)

ordem2 = r.sort_values("entradas")
fig = go.Figure([
    go.Bar(name="Entradas", y=ordem2["atendente"], x=ordem2["entradas"], orientation="h",
           marker_color=AZUL, marker_cornerradius=4, hovertemplate="%{y}: %{x} entradas<extra></extra>"),
    go.Bar(name="Vendas", y=ordem2["atendente"], x=ordem2["vendas"], orientation="h",
           marker_color=LARANJA, marker_cornerradius=4, hovertemplate="%{y}: %{x} vendas<extra></extra>"),
])
base_layout(fig, height=max(320, 34 * len(ordem2)), title="Captação × vendas", barmode="group")
c2.plotly_chart(fig, use_container_width=True)

c3, c4 = st.columns(2)
ordem3 = r.sort_values("entradas")
fig = go.Figure([
    go.Bar(name=nome, y=ordem3["atendente"], x=ordem3[col], orientation="h", marker_color=cor,
           marker_line=dict(color="white", width=2),
           hovertemplate="%{y}<br>" + nome + ": %{x}<extra></extra>")
    for nome, col, cor in [("Ganhos", "ganhos_coorte", GANHO), ("Em aberto", "em_aberto", ABERTO),
                           ("Perdidos", "perdidos_coorte", PERDIDO)]
])
base_layout(fig, height=max(320, 34 * len(ordem3)), title="Situação atual dos negócios criados no período",
            barmode="stack")
c3.plotly_chart(fig, use_container_width=True)

ordem4 = r.sort_values("receita")
fig = go.Figure(go.Bar(
    x=ordem4["receita"], y=ordem4["atendente"], orientation="h", marker_color=AZUL, marker_cornerradius=4,
    text=[fmt_brl(v) for v in ordem4["receita"]], textposition="outside",
    hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>"))
base_layout(fig, height=max(320, 34 * len(ordem4)), title="Receita das vendas ganhas")
c4.plotly_chart(fig, use_container_width=True)

# ---------------- Movimento diário ----------------
st.subheader("Movimento de conversão")
quem = st.selectbox("Visão", ["Geral"] + r["atendente"].tolist())
coh_m = cohort if quem == "Geral" else cohort[cohort["atendente"] == quem]
ven_m = vendas if quem == "Geral" else vendas[vendas["atendente"] == quem]
mov = movimento_diario(coh_m, ven_m, inicio, fim)

m1, m2 = st.columns(2)
fig = go.Figure([
    go.Scatter(name="Entradas", x=mov["dia"], y=mov["entradas"], mode="lines+markers",
               line=dict(color=AZUL, width=2), marker=dict(size=8)),
    go.Scatter(name="Vendas", x=mov["dia"], y=mov["vendas"], mode="lines+markers",
               line=dict(color=LARANJA, width=2), marker=dict(size=8)),
])
base_layout(fig, title=f"Entradas e vendas por dia · {quem}", hovermode="x unified")
fig.update_xaxes(tickformat="%d/%m")
m1.plotly_chart(fig, use_container_width=True)

fig = go.Figure(go.Scatter(
    name="Conversão acumulada", x=mov["dia"], y=mov["conv_acumulada"], mode="lines",
    line=dict(color=AZUL, width=2), fill="tozeroy", fillcolor="rgba(42,120,214,0.12)",
    hovertemplate="%{x|%d/%m}: %{y:.1%}<extra></extra>"))
base_layout(fig, title=f"Conversão acumulada no período · {quem}", hovermode="x unified")
fig.update_xaxes(tickformat="%d/%m")
fig.update_yaxes(tickformat=".0%", rangemode="tozero")
m2.plotly_chart(fig, use_container_width=True)

# ---------------- Tabela ----------------
st.subheader("Tabela detalhada")
tabela = resumo.rename(columns={
    "atendente": "Atendente", "leads": "Leads novos", "entradas": "Entradas",
    "vendas": "Vendas", "conv_fluxo": "Conversão fluxo", "ganhos_coorte": "Ganhos (coorte)",
    "em_aberto": "Em aberto", "perdidos_coorte": "Perdidos", "conv_coorte": "Conversão coorte",
    "perda": "Taxa de perda", "receita": "Receita", "ticket_medio": "Ticket médio"})
tabela = tabela[["Atendente", "Leads novos", "Entradas", "Vendas", "Conversão fluxo", "Ganhos (coorte)",
                 "Em aberto", "Perdidos", "Conversão coorte", "Taxa de perda", "Receita", "Ticket médio"]]
st.dataframe(
    tabela.style.format({"Conversão fluxo": fmt_pct, "Conversão coorte": fmt_pct, "Taxa de perda": fmt_pct,
                         "Receita": fmt_brl, "Ticket médio": fmt_brl}),
    use_container_width=True, hide_index=True)
st.download_button("Baixar CSV", tabela.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                   file_name=f"conversao_{inicio}_{fim}.csv", mime="text/csv")

with st.expander("Como as métricas são calculadas"):
    st.markdown("""
- **Leads novos atribuídos**: leads criados no período, agrupados pelo atendente atual do lead.
- **Entradas**: negócios criados no período (captação no funil), pelo atendente responsável.
- **Vendas**: negócios com status *ganho* cuja data de ganho cai no período.
- **Conversão (fluxo)**: vendas ÷ entradas no mesmo período.
- **Conversão (coorte)**: dos negócios criados no período, quantos já estão ganhos.
- **Taxa de perda**: dos negócios criados no período, quantos estão perdidos.
""")
