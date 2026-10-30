# Dashboard de Conversão por Atendente (DataCrazy)

Painel em Python (Streamlit + Plotly) que lê a API do CRM DataCrazy e mostra, por atendente e no geral:

- leads novos atribuídos e negócios criados (captação/entrada)
- vendas ganhas, receita e ticket médio
- taxa de conversão (fluxo e coorte) e taxa de perda
- movimento diário de entradas × vendas e conversão acumulada
- tabela detalhada com exportação CSV

## Como rodar

1. Coloque a chave da API no `.env` (veja `.env.example`):
   ```
   CGAVE_API=sua_chave
   ```
2. Suba o container:
   ```
   docker compose up -d --build
   ```
3. Acesse http://localhost:8501

## Métricas

| Métrica | Cálculo |
|---|---|
| Leads novos | leads criados no período, pelo atendente atual do lead |
| Entradas | negócios criados no período, pelo atendente do negócio |
| Vendas | negócios ganhos com data de ganho no período |
| Conversão (fluxo) | vendas ÷ entradas do período |
| Conversão (coorte) | negócios criados no período que já estão ganhos ÷ entradas |
| Taxa de perda | negócios criados no período que estão perdidos ÷ entradas |

Os dados ficam em cache por 15 minutos. O botão "Atualizar dados" força uma nova busca.
O cliente respeita o limite da API (60 req/min por rota) e divide a busca por janelas de data quando passa de 10.000 registros.

## Estrutura

- `app/datacrazy.py`: cliente da API (paginação, rate limit)
- `app/metrics.py`: cálculo das métricas
- `app/main.py`: interface Streamlit
