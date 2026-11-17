import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx
from fastapi import HTTPException

from app.config import settings
from app.db import db

log: logging.Logger = logging.getLogger("live")


TIPO_AVISO: dict[str, str] = {
    "Normal": "info",
    "Com Problemas": "alerta",
    "Interrompida": "urgente",
}


# --- Trilhos ----------------------------------------------------------
def traduz_status(s: dict[str, Any] | None) -> str:
    """Converte o status da API Trilhos para os rótulos usados no front."""
    if not s:
        return "Sem dados"

    classe: str | None = s.get("classificacao")
    situacao: str = (s.get("situacao") or "").lower()

    if classe == "ignorar":
        return "Fechada"

    if classe == "operacional":
        return "Normal" if "normal" in situacao else "Com Problemas"

    if "paralis" in situacao or "interromp" in situacao:
        return "Interrompida"

    return "Com Problemas"


async def atualiza_trilhos(http: httpx.AsyncClient) -> int:
    """Busca o status, grava em `status_linhas` e cria avisos quando muda.
    Retorna quantos segundos esperar até a próxima consulta."""
    r: httpx.Response = await http.get(
        settings.trilhos_url,
        headers={"Authorization": f"Api-Key {settings.trilhos_api_key}"},
    )

    if r.status_code == 429:
        return int(r.headers.get("Retry-After", 3600))

    r.raise_for_status()

    agora: datetime = datetime.now(UTC)

    for empresa in r.json().get("empresas", []):
        for linha in empresa.get("linhas", []):
            codigo = str(linha["codigo"])
            s: dict[str, str] | None = linha.get("status")
            status: str = traduz_status(s)
            antigo: dict[str, Any] | None = await db.status_linhas.find_one(
                {"_id": codigo}
            )

            await db.status_linhas.replace_one(
                {"_id": codigo},
                {
                    "_id": codigo,
                    "nome": linha.get("nome"),
                    "empresa": empresa.get("nome"),
                    "status": status,
                    "situacao": (s or {}).get("situacao"),
                    "descricao": (s or {}).get("descricao"),
                    "atualizado_em": (s or {}).get("atualizado_em"),
                    "coletado_em": agora,
                },
                upsert=True,
            )

            mudou: bool = (antigo or {}).get("situacao") != (s or {}).get("situacao")
            primeira_normal: bool = antigo is None and status == "Normal"

            if s and mudou and not primeira_normal and status in TIPO_AVISO:
                await db.avisos.insert_one(
                    {
                        "linha": linha.get("nome"),
                        "empresa": empresa.get("nome"),
                        "titulo": s.get("situacao"),
                        "descricao": s.get("descricao")
                        or f"{linha.get('nome')}: {s.get('situacao')}",
                        "tipo": TIPO_AVISO[status],
                        "criado_em": agora,
                    }
                )

    return settings.trilhos_intervalo_s


async def loop_trilhos() -> NoReturn:
    async with httpx.AsyncClient(timeout=20) as http:
        while True:
            espera: int = settings.trilhos_intervalo_s

            try:
                espera: int = await atualiza_trilhos(http)

            except asyncio.CancelledError:
                raise

            except Exception as e:  # não derruba o servidor
                log.warning("Falha ao consultar API Trilhos: %s", e)

            await asyncio.sleep(espera)


async def mapa_status() -> dict[str, dict[str, Any]]:
    """{codigo_da_linha: doc} — poucas dezenas de documentos."""
    return {d["_id"]: d async for d in db.status_linhas.find({})}


# --- Olho Vivo ----------------------------------------------------------
class OlhoVivo:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(base_url=settings.olhovivo_url, timeout=15)

    async def _login(self) -> None:
        r: httpx.Response = await self.http.post(
            "/Login/Autenticar", params={"token": settings.olhovivo_token}
        )

        if r.text.strip().lower() != "true":
            raise HTTPException(502, "Olho Vivo recusou o token")

    async def get(self, caminho: str, **params):
        if not settings.olhovivo_token:
            raise HTTPException(503, "OLHOVIVO_TOKEN não configurado")

        try:
            for _ in range(2):  # 2ª tentativa depois de autenticar
                r: httpx.Response = await self.http.get(caminho, params=params)

                if r.status_code == 401:
                    await self._login()
                    continue

                r.raise_for_status()
                return r.json()

        except httpx.HTTPError as e:
            raise HTTPException(502, f"Olho Vivo indisponível: {e}")

        raise HTTPException(502, "Olho Vivo: não foi possível autenticar")


olho_vivo = OlhoVivo()
