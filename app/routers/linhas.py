import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pymongo.asynchronous.cursor import AsyncCursor

from ..db import db
from ..live import mapa_status
from ..util import normaliza

router = APIRouter(tags=["linhas"])


def linha_out(d: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    """Mesmo formato dos objetos `linha` do front (numero, nome, cor, status, tipo, operadora).
    O status ao vivo só existe para Metrô/Trem cobertos pela API Trilhos."""
    st: str = "Sem dados"

    if d["tipo"] in ("Metrô", "Trem") and d["numero"] in status:
        st: str = status[d["numero"]]["status"]

    return {
        "id": d["_id"],
        "numero": d["numero"],
        "nome": d["nome"],
        "cor": d["cor"],
        "tipo": d["tipo"],
        "operadora": d.get("operadora"),
        "status": st,
    }


@router.get("/linhas")
async def listar_linhas(
    tipo: str | None = Query(None, description="Metrô, Trem ou Ônibus"),
    q: str | None = None,
    limite: int = Query(50, ge=1, le=200),
    pular: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    filtro: dict[str, Any] = {}

    if tipo and tipo != "Todos":
        filtro["tipo"] = tipo

    if q:
        filtro["busca"] = {"$regex": re.escape(normaliza(q))}

    status: dict[str, dict[str, Any]] = await mapa_status()
    docs: AsyncCursor[dict[str, Any]] = (
        db.linhas.find(filtro)
        .sort([("tipo", 1), ("numero", 1)])
        .skip(pular)
        .limit(limite)
    )

    return [linha_out(d, status) async for d in docs]


@router.get("/linhas/{linha_id}")
async def obter_linha(linha_id: str) -> dict[str, Any]:
    d: dict[str, Any] | None = await db.linhas.find_one({"_id": linha_id})

    if not d:
        raise HTTPException(404, "Linha não encontrada")

    return linha_out(d, await mapa_status())


@router.get("/linhas/{linha_id}/shape")
async def shape_da_linha(linha_id: str) -> dict[str, Any]:
    """Pontos [lat, lon] para desenhar a linha no Leaflet (uma das viagens da linha)."""
    viagem: dict[str, Any] | None = await db.viagens.find_one(
        {"route_id": linha_id, "shape_id": {"$ne": None}}
    )

    shape: dict[str, Any] | None = viagem and await db.shapes.find_one(
        {"_id": viagem["shape_id"]}
    )

    if not shape:
        raise HTTPException(404, "Linha sem shape")
    
    return {"pontos": shape["pontos"]}


@router.get("/buscar")
async def buscar(q: str = Query(min_length=2), limite: int = Query(10, ge=1, le=30)) -> list[dict[str, Any]]:
    """Sugestões para os campos de busca (linhas + paradas/estações)."""
    rx: dict[str, str] = {"$regex": re.escape(normaliza(q))}
    saida: list[dict[str, Any]] = []

    async for d in db.linhas.find({"busca": rx}).limit(limite):
        saida.append(
            {
                "categoria": "linha",
                "id": d["_id"],
                "nome": f"Linha {d['numero']} - {d['nome']}",
                "tipo": d["tipo"],
                "operadora": d.get("operadora"),
            }
        )
    
    async for d in db.paradas.find({"busca": rx}).sort("estacao", -1).limit(limite):
        saida.append(
            {
                "categoria": "parada",
                "id": d["_id"],
                "nome": d["nome"],
                "tipo": "Estação" if d.get("estacao") else "Parada",
            }
        )
    
    return saida
