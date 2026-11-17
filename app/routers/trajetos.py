import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pymongo.asynchronous.cursor import AsyncCursor

from ..db import db
from ..live import mapa_status
from ..util import normaliza
from .linhas import linha_out

router = APIRouter(tags=["trajetos"])


async def achar_paradas(termo: str) -> list[dict[str, Any]]:
    if ":" in termo:  # veio um id de /buscar
        p: dict[str, Any] | None = await db.paradas.find_one({"_id": termo})
        return [p] if p else []
    
    rx: dict[str, str] = {"$regex": re.escape(normaliza(termo))}
    return await db.paradas.find({"busca": rx}).limit(30).to_list(None)


@router.get("/trajetos")
async def trajetos(origem: str, destino: str, limite: int = Query(10, ge=1, le=30)):
    """Linhas DIRETAS (sem baldeação) de `origem` até `destino`, com duração estimada.
    Aceita nome ('Estação Sé') ou id de parada (de /buscar). Não há horários de saída."""
    ori, des = await achar_paradas(origem), await achar_paradas(destino)

    if not ori or not des:
        raise HTTPException(404, "Origem ou destino não encontrado")
    
    nome_ori: dict[str, str] = {p["_id"]: p["nome"] for p in ori}
    nome_des: dict[str, str] = {p["_id"]: p["nome"] for p in des}

    padroes: AsyncCursor[dict[str, Any]] = (
        db.padroes.find(
            {
                "$and": [
                    {"paradas": {"$in": list(nome_ori)}},
                    {"paradas": {"$in": list(nome_des)}},
                ]
            }
        )
        .sort("n_viagens", -1)
        .limit(2000)
    )

    melhor: dict[str, dict[str, Any]] = {}  # route_id -> trajeto mais curto
    async for d in padroes:
        ps: list[dict[str, Any]] = d["paradas"]
        pares: list[tuple[int, int, int]] = [
            (j - i, i, j)
            for i, a in enumerate(ps)
            if a in nome_ori
            for j, b in enumerate(ps)
            if j > i and b in nome_des
        ]

        if not pares:
            continue

        _, i, j = min(pares)
        duracao: int = d["minutos"][j] - d["minutos"][i]
        atual: dict[str, Any] | None = melhor.get(d["route_id"])

        if not atual or duracao < atual["duracao"]:
            melhor[d["route_id"]] = {"duracao": duracao, "i": i, "j": j, "padrao": d}

    escolhidos: list[tuple[str, dict[str, Any]]] = sorted(melhor.items(), key=lambda kv: kv[1]["duracao"])[:limite]
    linhas: dict[str, dict[str, Any]] = {
        l["_id"]: l
        async for l in db.linhas.find({"_id": {"$in": [r for r, _ in escolhidos]}})
    }

    status: dict[str, dict[str, Any]] = await mapa_status()
    resultado: list[dict[str, Any]] = []

    for rota, m in escolhidos:
        if rota not in linhas:
            continue
        
        linha, ps = linha_out(linhas[rota], status), m["padrao"]["paradas"]
        resultado.append(
            {
                "origem": nome_ori[ps[m["i"]]],
                "destino": nome_des[ps[m["j"]]],
                "transporte": linha["tipo"],
                "tempo": f"{max(m['duracao'], 1)} min",  # formato do RotaCard
                "linha": linha,
                "paradas": m["j"] - m["i"],
            }
        )
    
    return resultado
