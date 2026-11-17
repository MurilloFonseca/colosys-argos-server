from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.results import DeleteResult

from ..db import db
from ..schemas import RelatoIn
from ..security import usuario_atual
from ..util import TZ

router = APIRouter(prefix="/relatos", tags=["relatos"])


def _relato_out(d: dict[str, Any]) -> dict[str, Any]:
    """Formato do ComentarioCard (transporte, linha, data, nota, comentario).
    Não expõe quem escreveu."""
    notas: list[int] = [n for n in d["avaliacoes"].values() if n]

    return {
        "id": str(d["_id"]),
        "transporte": d["transporte"],
        "linha_id": d.get("linha_id"),
        "linha": d.get("linha"),
        "data": d["criado_em"].astimezone(TZ).strftime("%d/%m/%Y"),
        "nota": round(sum(notas) / len(notas)) if notas else 0,
        "avaliacoes": d["avaliacoes"],
        "comentario": d["comentario"],
    }


@router.get("")
async def listar(
    linha_id: str | None = None,
    transporte: str | None = None,
    limite: int = Query(20, ge=1, le=100),
    pular: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    filtro: dict[str, str] = {
        k: v for k, v in {"linha_id": linha_id, "transporte": transporte}.items() if v
    }

    docs: AsyncCursor[dict[str, Any]] = (
        db.relatos.find(filtro).sort("criado_em", -1).skip(pular).limit(limite)
    )

    return [_relato_out(d) async for d in docs]


@router.post("", status_code=201)
async def criar(dados: RelatoIn, usuario=Depends(usuario_atual)) -> dict[str, Any]:
    nome_linha = None

    if dados.linha_id:
        linha: dict[str, Any] | None = await db.linhas.find_one({"_id": dados.linha_id})

        if not linha:
            raise HTTPException(404, "Linha não encontrada")

        nome_linha: str = f"Linha {linha['numero']} - {linha['nome']}"

    doc: dict[str, Any] = {
        "usuario_id": usuario["_id"],
        "transporte": dados.transporte,
        "linha_id": dados.linha_id,
        "linha": nome_linha,
        "avaliacoes": dados.avaliacoes.model_dump(),
        "comentario": dados.comentario.strip(),
        "criado_em": datetime.now(UTC),
    }

    doc["_id"] = (await db.relatos.insert_one(doc)).inserted_id
    return _relato_out(doc)


@router.delete("/{relato_id}", status_code=204)
async def apagar(relato_id: str, usuario=Depends(usuario_atual)) -> None:
    try:
        oid = ObjectId(relato_id)

    except InvalidId:
        raise HTTPException(404, "Relato não encontrado")

    r: DeleteResult = await db.relatos.delete_one(
        {"_id": oid, "usuario_id": usuario["_id"]}
    )

    if not r.deleted_count:
        raise HTTPException(404, "Relato não encontrado")
