from typing import Any

from fastapi import APIRouter, HTTPException

from ..db import db

router = APIRouter(tags=["tarifas"])


def tarifa_out(d: dict[str, Any]) -> dict[str, Any]:
    seg: int | None = d.get("duracao_baldeacao_s")
    return {
        "id": d["_id"],
        "preco": d["preco"],
        "moeda": d["moeda"],
        "operadora": d.get("operadora"),
        "pagamento": {"0": "a bordo", "1": "antes de embarcar"}.get(d.get("pagamento")),
        "baldeacoes": d.get("baldeacoes"),  # None = ilimitadas ou não informado
        "duracao_baldeacao_min": seg // 60 if seg else None,
    }


@router.get("/tarifas")
async def listar_tarifas(fonte: str | None = None) -> list[dict[str, Any]]:
    filtro = {"fonte": fonte} if fonte else {}
    return [tarifa_out(d) async for d in db.tarifas.find(filtro).sort("preco", 1)]


@router.get("/tarifas/{tarifa_id}")
async def obter_tarifa(tarifa_id: str) -> dict[str, Any]:
    d: dict[str, Any] | None = await db.tarifas.find_one({"_id": tarifa_id})

    if not d:
        raise HTTPException(404, "Tarifa não encontrada")

    regras: list[dict[str, Any]] = (
        await db.regras_tarifa.find({"fare_id": tarifa_id}).limit(500).to_list(None)
    )

    return tarifa_out(d) | {
        "regras": [
            {
                "linha_id": r["route_id"],
                "origem_zona": r["origem_zona"],
                "destino_zona": r["destino_zona"],
                "contem_zona": r["contem_zona"],
            }
            for r in regras
        ]
    }


@router.get("/linhas/{linha_id}/tarifa")
async def tarifa_da_linha(linha_id: str) -> list[dict[str, Any]]:
    """Tarifas ligadas à linha por fare_rules. Se a fonte não tem nenhuma regra
    para a linha, devolve as tarifas sem regras (tarifa única do feed)."""
    linha: dict[str, Any] | None = await db.linhas.find_one({"_id": linha_id})

    if not linha:
        raise HTTPException(404, "Linha não encontrada")

    regras: list[dict[str, Any]] = await db.regras_tarifa.find(
        {"route_id": linha_id}
    ).to_list(None)
    ids: list[str] = list({r["fare_id"] for r in regras})

    if ids:
        filtro: dict[str, dict[str, list[str]]] = {"_id": {"$in": ids}}

    else:
        com_regra: list[dict[str, Any]] = await db.regras_tarifa.distinct(
            "fare_id", {"fonte": linha["fonte"]}
        )
        filtro: dict[str, Any] = {"fonte": linha["fonte"], "_id": {"$nin": com_regra}}

    return [tarifa_out(d) async for d in db.tarifas.find(filtro)]
