from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..db import db
from ..live import olho_vivo
from ..util import TZ

router = APIRouter(tags=["tempo real"])


@router.get("/avisos")
async def avisos(limite: int = Query(30, ge=1, le=100)) -> list[dict[str, Any]]:
    """Avisos gerados quando o status de uma linha muda (API Trilhos)."""
    saida: list[dict[str, Any]] = []

    async for a in db.avisos.find({}).sort("criado_em", -1).limit(limite):
        quando: datetime = a["criado_em"].astimezone(TZ)

        saida.append(
            {
                "id": str(a["_id"]),
                "titulo": a["titulo"],
                "descricao": a["descricao"],
                "horario": quando.strftime("%H:%M"),
                "data": quando.strftime("%d/%m/%Y"),
                "tipo": a["tipo"],
                "linha": a["linha"],
            }
        )

    return saida


@router.get("/onibus/linhas/{linha_id}/posicoes")
async def posicoes_onibus(linha_id: str) -> dict[str, Any]:
    """Posição ao vivo dos ônibus de uma linha da SPTrans (Olho Vivo)."""
    linha: dict[str, Any] | None = await db.linhas.find_one(
        {"_id": linha_id, "tipo": "Ônibus"}
    )

    if not linha:
        raise HTTPException(404, "Linha de ônibus não encontrada")

    alvo: str = linha["numero"].replace("/", "-")

    # O Olho Vivo usa um código próprio (cl), um por sentido; ele é achado pelo letreiro.
    achadas: list[dict[str, Any]] = await olho_vivo.get(
        "/Linha/Buscar", termosBusca=alvo.split("-")[0]
    )
    iguais: list[dict[str, Any]] = [
        x for x in achadas if f"{x['lt']}-{x['tl']}" == alvo
    ] or achadas
    veiculos: list[dict[str, Any]] = []

    for x in iguais:
        dados: dict[str, Any] = await olho_vivo.get(
            "/Posicao/Linha", codigoLinha=x["cl"]
        )

        for v in dados.get("vs", []):
            veiculos.append(
                {
                    "prefixo": v["p"],
                    "acessivel": v["a"],
                    "atualizado": v["ta"],
                    "lat": v["py"],
                    "lon": v["px"],
                    "sentido": x["sl"],
                }
            )

    return {"linha": linha["numero"], "veiculos": veiculos}


@router.get("/onibus/paradas/{parada_id}/previsao")
async def previsao_parada(parada_id: str) -> list[dict[str, Any]]:
    """Previsão de chegada na parada (Olho Vivo). O stop_id do GTFS da SPTrans é o código da parada."""
    codigo: str = parada_id.split(":", 1)[-1]
    return await olho_vivo.get("/Previsao/Parada", codigoParada=codigo)
