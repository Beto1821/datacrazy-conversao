"""Cliente mínimo da API DataCrazy (https://docs.datacrazy.io)."""
import time
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = "https://api.g1.datacrazy.io/api/v1"
PAGE_SIZE = 1000
MAX_SKIP = 10000  # a API não pagina além disso; acima dividimos a janela de datas


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class DataCrazyClient:
    def __init__(self, token: str, timeout: int = 60):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(6):
            resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", 30)) + 1)
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            # limite de 60 req/min por rota: espera o reset se a cota acabou
            if resp.headers.get("X-RateLimit-Remaining") == "0":
                time.sleep(int(resp.headers.get("X-RateLimit-Reset", 60)) + 1)
            return resp.json()
        resp.raise_for_status()
        raise RuntimeError(f"Falha ao consultar {path}")

    def _paginate_window(self, path: str, filters: dict, start: datetime, end: datetime,
                         start_key: str, end_key: str) -> list[dict]:
        """Busca todos os registros da janela; divide a janela se passar do limite de skip."""
        params = {f"filter[{k}]": v for k, v in filters.items()}
        params[f"filter[{start_key}]"] = _iso(start)
        params[f"filter[{end_key}]"] = _iso(end)

        items: list[dict] = []
        skip = 0
        while True:
            page = self._get(path, {**params, "skip": skip, "take": PAGE_SIZE})
            data = page.get("data", [])
            items.extend(data)
            if len(data) < PAGE_SIZE:
                return items
            skip += PAGE_SIZE
            if skip >= MAX_SKIP:
                break

        if end - start <= timedelta(minutes=1):
            return items
        mid = start + (end - start) / 2
        return (self._paginate_window(path, filters, start, mid, start_key, end_key)
                + self._paginate_window(path, filters, mid + timedelta(milliseconds=1), end, start_key, end_key))

    def attendants(self) -> list[dict]:
        return self._get("/attendants/crm").get("data", [])

    def pipelines(self) -> list[dict]:
        return self._get("/pipelines").get("data", [])

    def leads_created(self, start: datetime, end: datetime) -> list[dict]:
        return self._paginate_window("/leads", {}, start, end,
                                     "createdAtGreaterOrEqual", "createdAtLessOrEqual")

    def businesses_created(self, start: datetime, end: datetime) -> list[dict]:
        return self._paginate_window("/businesses", {}, start, end,
                                     "createdAtGreaterOrEqual", "createdAtLessOrEqual")

    def businesses_won_moved(self, start: datetime, end: datetime) -> list[dict]:
        """Negócios ganhos movidos no intervalo (superset das vendas fechadas no período)."""
        return self._paginate_window("/businesses", {"status": "won"}, start, end,
                                     "lastMovedAfter", "lastMovedBefore")
