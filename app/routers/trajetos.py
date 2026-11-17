import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..db import db
from ..live import mapa_status
from ..util import TZ, hhmm, normaliza
from .linhas import linha_out

router = APIRouter(tags=["trajetos"])


def agora() -> tuple[date, int]:
    n: datetime = datetime.now(TZ)
    return n.date(), n.hour * 3600 + n.minute * 60 + n.second


async def servicos_validos(dia: date) -> list[dict[str, Any] | None] | None:
    """service_ids ativos no dia (+ None, p/ feeds sem calendar.txt).
    Retorna None se nenhum calendário foi importado (não filtra)."""
    if not await db.calendarios.estimated_document_count():
        return None

    ds: str = dia.strftime("%Y%m%d")
    ids: list[dict[str, Any]] = [
        c["_id"]
        async for c in db.calendarios.find(
            {
                "inicio": {"$lte": ds},
                "fim": {"$gte": ds},
                f"dias.{dia.weekday()}": True,
            },
            {"_id": 1},
        )
    ]

    return ids + [None]


@router.get("/paradas/{parada_id}/horarios")
async def proximos_horarios(
    parada_id: str, limite: int = Query(10, ge=1, le=50)
) -> list[dict[str, Any]]:
    """Próximas partidas previstas (horário programado do GTFS) numa parada."""
    dia, seg = agora()
    filtro: dict[str, Any] = {"stop_id": parada_id, "saida_s": {"$gte": seg}}
    servicos: list[dict[str, Any] | None] | None = await servicos_validos(dia)

    if servicos is not None:
        filtro["service_id"] = {"$in": servicos}

    hs: list[dict[str, Any]] = (
        await db.horarios.find(filtro).sort("saida_s", 1).limit(limite).to_list(None)
    )

    viagens: dict[str, Any] = {
        v["_id"]: v
        async for v in db.viagens.find({"_id": {"$in": [h["trip_id"] for h in hs]}})
    }

    linhas: dict[str, Any] = {
        l["_id"]: l
        async for l in db.linhas.find({"_id": {"$in": [h["route_id"] for h in hs]}})
    }

    status: dict[str, dict[str, Any]] = await mapa_status()

    return [
        {
            "horario": hhmm(h["saida_s"]),
            "linha": linha_out(linhas[h["route_id"]], status)
            if h["route_id"] in linhas
            else None,
            "destino": viagens.get(h["trip_id"], {}).get("destino", ""),
        }
        for h in hs
    ]


async def achar_paradas(termo: str) -> list[dict[str, Any]]:
    if ":" in termo:  # veio um id de /buscar
        p: dict[str, Any] | None = await db.paradas.find_one({"_id": termo})
        return [p] if p else []

    rx: dict[str, str] = {"$regex": re.escape(normaliza(termo))}
    return await db.paradas.find({"busca": rx}).limit(30).to_list(None)


@router.get("/trajetos")
async def trajetos(
    origem: str, destino: str, limite: int = Query(10, ge=1, le=30)
) -> list[dict[str, Any]]:
    """Viagens DIRETAS (sem baldeação) de `origem` até `destino`, a partir de agora.
    Aceita nome ('Estação Sé') ou id de parada (de /buscar)."""
    ori, des = await achar_paradas(origem), await achar_paradas(destino)

    if not ori or not des:
        raise HTTPException(404, "Origem ou destino não encontrado")

    nome_ori: dict[str, str] = {p["_id"]: p["nome"] for p in ori}
    nome_des: dict[str, str] = {p["_id"]: p["nome"] for p in des}

    dia, seg = agora()
    filtro: dict[str, Any] = {
        "stop_id": {"$in": list(nome_ori)},
        "saida_s": {"$gte": seg},
    }
    servicos: list[dict[str, Any] | None] | None = await servicos_validos(dia)

    if servicos is not None:
        filtro["service_id"] = {"$in": servicos}

    partidas: list[dict[str, Any]] = (
        await db.horarios.find(filtro).sort("saida_s", 1).limit(5000).to_list(None)
    )
    por_viagem: dict[str, dict[str, Any]] = {}
    for h in partidas:
        por_viagem.setdefault(h["trip_id"], h)

    chegadas: list[dict[str, Any]] = []
    ids: list = list(por_viagem)

    for i in range(0, len(ids), 2000):
        chegadas += await db.horarios.find(
            {"trip_id": {"$in": ids[i : i + 2000]}, "stop_id": {"$in": list(nome_des)}}
        ).to_list(None)

    # Primeira partida de cada linha que passa pela origem e depois pelo destino.
    melhor: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for c in chegadas:
        o: dict[str, Any] = por_viagem[c["trip_id"]]

        if c["seq"] <= o["seq"]:
            continue

        atual: tuple[dict[str, Any], dict[str, Any]] | None = melhor.get(o["route_id"])

        if not atual or o["saida_s"] < atual[0]["saida_s"]:
            melhor[o["route_id"]] = (o, c)

    escolhidos: list[tuple[dict[str, Any], dict[str, Any]]] = sorted(
        melhor.values(), key=lambda par: par[0]["saida_s"]
    )[:limite]

    linhas: dict[str, Any] = {
        l["_id"]: l
        async for l in db.linhas.find(
            {"_id": {"$in": [o["route_id"] for o, _ in escolhidos]}}
        )
    }

    status: dict[str, dict[str, Any]] = await mapa_status()
    resultado: list[dict[str, Any]] = []

    for o, c in escolhidos:
        linha: dict[str, Any] = linha_out(linhas[o["route_id"]], status)
        minutos: int = max(0, round((c["chegada_s"] - o["saida_s"]) / 60))
        resultado.append(
            {
                "origem": nome_ori[o["stop_id"]],
                "destino": nome_des[c["stop_id"]],
                "transporte": linha["tipo"],
                "tempo": f"{minutos} min",  # formato do RotaCard
                "linha": linha,
                "saida": hhmm(o["saida_s"]),
                "chegada": hhmm(c["chegada_s"]),
                "paradas": c["seq"] - o["seq"],
            }
        )

    return resultado
