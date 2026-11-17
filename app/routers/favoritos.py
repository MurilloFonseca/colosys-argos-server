from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.results import DeleteResult

from ..db import db
from ..live import mapa_status
from ..schemas import FavLinhaIn, FavTrajetoIn
from ..security import usuario_atual
from .linhas import linha_out

router = APIRouter(prefix="/favoritos", tags=["favoritos"])


def _trajeto_out(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(d["_id"]),
        "origem": d["origem"],
        "destino": d["destino"],
        "transporte": d.get("transporte"),
        "tempo": d.get("tempo"),
        "favorito": True,
    }


@router.get("")
async def listar(usuario=Depends(usuario_atual)) -> dict[str, Any]:
    """{linhas: [...], trajetos: [...]}, nos formatos usados em Favoritos.jsx."""
    docs: list[dict[str, Any]] = (
        await db.favoritos.find({"usuario_id": usuario["_id"]})
        .sort("criado_em", -1)
        .to_list(None)
    )

    ids: list[str] = [d["linha_id"] for d in docs if d["tipo"] == "linha"]
    linhas: dict[str, dict[str, Any]] = {
        l["_id"]: l async for l in db.linhas.find({"_id": {"$in": ids}})
    }
    status: dict[str, dict[str, Any]] = await mapa_status()

    return {
        "linhas": [
            linha_out(linhas[i], status) | {"favorito": True}
            for i in ids
            if i in linhas
        ],
        "trajetos": [_trajeto_out(d) for d in docs if d["tipo"] == "trajeto"],
    }


@router.post("/linhas", status_code=201)
async def favoritar_linha(
    dados: FavLinhaIn, usuario=Depends(usuario_atual)
) -> dict[str, Any]:
    if not await db.linhas.find_one({"_id": dados.linha_id}, {"_id": 1}):
        raise HTTPException(404, "Linha não encontrada")

    await db.favoritos.update_one(
        {"usuario_id": usuario["_id"], "tipo": "linha", "linha_id": dados.linha_id},
        {"$setOnInsert": {"criado_em": datetime.now(UTC)}},
        upsert=True,
    )

    return {"linha_id": dados.linha_id, "favorito": True}


@router.delete("/linhas/{linha_id}", status_code=204)
async def desfavoritar_linha(linha_id: str, usuario=Depends(usuario_atual)) -> None:
    await db.favoritos.delete_one(
        {"usuario_id": usuario["_id"], "tipo": "linha", "linha_id": linha_id}
    )


@router.post("/trajetos", status_code=201)
async def favoritar_trajeto(
    dados: FavTrajetoIn, usuario=Depends(usuario_atual)
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        **dados.model_dump(),
        "usuario_id": usuario["_id"],
        "tipo": "trajeto",
        "criado_em": datetime.now(UTC),
    }

    doc["_id"] = (await db.favoritos.insert_one(doc)).inserted_id
    return _trajeto_out(doc)


@router.delete("/trajetos/{trajeto_id}", status_code=204)
async def desfavoritar_trajeto(trajeto_id: str, usuario=Depends(usuario_atual)) -> None:
    try:
        oid = ObjectId(trajeto_id)

    except InvalidId:
        raise HTTPException(404, "Trajeto não encontrado")

    r: DeleteResult = await db.favoritos.delete_one(
        {"_id": oid, "usuario_id": usuario["_id"], "tipo": "trajeto"}
    )

    if not r.deleted_count:
        raise HTTPException(404, "Trajeto não encontrado")
