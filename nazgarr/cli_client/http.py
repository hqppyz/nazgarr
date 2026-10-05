"""Il client HTTP del CLI: le stesse API JSON della web UI, con una API key
(X-Api-Key) o, solo per login e setup, il token del login. Gli errori del
server arrivano come codice e parametri e si mostrano con lo stesso testo
inglese dell'interfaccia (messages_en.json)."""

from collections.abc import Callable

import httpx

from nazgarr.core.errors import english

TIMEOUT_SECONDS = 60.0


def _default_client(base_url: str, headers: dict[str, str]) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=headers, timeout=TIMEOUT_SECONDS)


# Sostituibile nei test (un TestClient sull'app, senza rete).
CLIENT_FACTORY: Callable[[str, dict[str, str]], httpx.Client] = _default_client


def message(code: str, params: dict | None = None) -> str:
    return english(code, params)


class ApiError(Exception):
    def __init__(self, status: int, code: str, params: dict | None = None, text: str | None = None):
        self.status, self.code, self.params = status, code, params or {}
        super().__init__(text or message(code, params))


def _error(response: httpx.Response) -> ApiError:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict) and "code" in detail:
        return ApiError(response.status_code, detail["code"], detail.get("params"))
    if isinstance(detail, list):  # validazione di FastAPI
        text = "; ".join(f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
        return ApiError(response.status_code, "invalid_request", text=f"Invalid request: {text}")
    return ApiError(response.status_code, f"http_{response.status_code}",
                    text=str(detail) if detail else f"HTTP {response.status_code}")


class Api:
    def __init__(self, url: str, api_key: str | None = None, token: str | None = None):
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-Api-Key"] = api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.url = url.rstrip("/")
        self._client = CLIENT_FACTORY(self.url, headers)

    def request(self, method: str, path: str, *, json_body=None, params: dict | None = None):
        try:
            response = self._client.request(method, path, json=json_body,
                                            params={k: v for k, v in (params or {}).items() if v is not None})
        except httpx.HTTPError as exc:
            raise ApiError(0, "connection_failed", text=f"Cannot reach {self.url}: {exc}") from exc
        if response.status_code >= 400:
            raise _error(response)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str, **params):
        return self.request("GET", path, params=params)

    def post(self, path: str, body=None):
        return self.request("POST", path, json_body=body)

    def patch(self, path: str, body=None):
        return self.request("PATCH", path, json_body=body)

    def put(self, path: str, body=None):
        return self.request("PUT", path, json_body=body)

    def delete(self, path: str):
        return self.request("DELETE", path)
