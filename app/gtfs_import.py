"""Importa um GTFS (.zip) para o MongoDB.

Uso:  python -m app.gtfs_import <fonte> <arquivo.zip>
Ex.:  python -m app.gtfs_import sptrans gtfs_sptrans.zip
      python -m app.gtfs_import artesp  gtfs_artesp.zip

`fonte` é só um rótulo: vira prefixo dos ids (ex.: "sptrans:3766-10") para que
feeds diferentes não colidam. Reimportar a mesma fonte substitui os dados dela.
"""

import csv
import io
import sys
import zipfile
from collections import defaultdict

from pymongo import MongoClient

from .config import settings
from .util import normaliza

LOTE = 10_000
TIPOS = {"0": "Metrô", "1": "Metrô", "2": "Trem", "3": "Ônibus"}


def tipo_linha(route_type: str) -> str:
    if route_type in TIPOS:
        return TIPOS[route_type]
    try:  # tipos estendidos do GTFS (100=trem, 400=metrô, 700=ônibus)
        t = int(route_type)
    except ValueError:
        return "Ônibus"
    return "Trem" if 100 <= t < 200 else "Metrô" if 400 <= t < 500 else "Ônibus"


def segundos(hora: str):
    if not hora or not hora.strip():
        return None
    h, m, s = hora.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)  # pode passar de 24h, como no GTFS


def ler(z: zipfile.ZipFile, nome: str):
    if nome not in z.namelist():
        return
    with z.open(nome) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "utf-8-sig"))


def inserir_em_lotes(colecao, docs, nome):
    lote, total = [], 0
    for d in docs:
        lote.append(d)
        if len(lote) >= LOTE:
            colecao.insert_many(lote, ordered=False)
            total += len(lote)
            lote = []
            if total % 500_000 == 0:
                print(f"  {nome}: {total:,}")
    if lote:
        colecao.insert_many(lote, ordered=False)
        total += len(lote)
    print(f"  {nome}: {total:,}")


def importar(fonte: str, caminho: str):
    db = MongoClient(settings.mongo_url)[settings.mongo_db]
    p = lambda i: f"{fonte}:{i}"  # prefixo

    for nome in ("linhas", "paradas", "viagens", "horarios", "shapes", "calendarios"):
        db[nome].delete_many({"fonte": fonte})

    with zipfile.ZipFile(caminho) as z:
        agencias = {
            a.get("agency_id", ""): a["agency_name"] for a in ler(z, "agency.txt")
        }
        unica = next(iter(agencias.values())) if len(agencias) == 1 else None

        print("linhas...")
        linhas = []
        for r in ler(z, "routes.txt"):
            nome_curto, nome_longo = (
                r.get("route_short_name", ""),
                r.get("route_long_name", ""),
            )
            cor = (r.get("route_color") or "").strip()
            linhas.append(
                {
                    "_id": p(r["route_id"]),
                    "fonte": fonte,
                    "numero": nome_curto or r["route_id"],
                    "nome": nome_longo,
                    "cor": f"#{cor}" if cor else "#E5A000",
                    "tipo": tipo_linha(r.get("route_type", "3")),
                    "operadora": agencias.get(
                        r.get("agency_id", ""), unica or fonte.upper()
                    ),
                    "busca": normaliza(f"{nome_curto} {nome_longo}"),
                }
            )
        if linhas:
            db.linhas.insert_many(linhas)
        print(f"  linhas: {len(linhas):,}")

        print("paradas...")

        def paradas():
            for r in ler(z, "stops.txt"):
                try:
                    lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
                except KeyError, ValueError:
                    continue
                yield {
                    "_id": p(r["stop_id"]),
                    "fonte": fonte,
                    "nome": r.get("stop_name", ""),
                    "lat": lat,
                    "lon": lon,
                    "estacao": r.get("location_type") == "1",
                    "busca": normaliza(r.get("stop_name", "")),
                }

        inserir_em_lotes(db.paradas, paradas(), "paradas")

        print("calendário...")
        cals = [
            {
                "_id": p(r["service_id"]),
                "fonte": fonte,
                "inicio": r["start_date"],
                "fim": r["end_date"],
                "dias": [
                    r[d] == "1"
                    for d in (
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    )
                ],
            }
            for r in ler(z, "calendar.txt")
        ]
        if cals:
            db.calendarios.insert_many(cals)
        # Sem calendar.txt, service_id fica None e a viagem vale todos os dias.
        usa_calendario = bool(cals)

        print("viagens...")
        info_viagem = {}

        def viagens():
            for r in ler(z, "trips.txt"):
                servico = p(r["service_id"]) if usa_calendario else None
                info_viagem[r["trip_id"]] = (p(r["route_id"]), servico)
                yield {
                    "_id": p(r["trip_id"]),
                    "fonte": fonte,
                    "route_id": p(r["route_id"]),
                    "service_id": servico,
                    "shape_id": p(r["shape_id"]) if r.get("shape_id") else None,
                    "destino": r.get("trip_headsign", ""),
                    "sentido": r.get("direction_id", ""),
                }

        inserir_em_lotes(db.viagens, viagens(), "viagens")

        print("horários (stop_times)... pode demorar")

        def horarios():
            for r in ler(z, "stop_times.txt"):
                info = info_viagem.get(r["trip_id"])
                if not info:
                    continue
                chegada, saida = (
                    segundos(r.get("arrival_time")),
                    segundos(r.get("departure_time")),
                )
                if chegada is None and saida is None:
                    continue
                yield {
                    "fonte": fonte,
                    "trip_id": p(r["trip_id"]),
                    "stop_id": p(r["stop_id"]),
                    "seq": int(r["stop_sequence"]),
                    "chegada_s": chegada if chegada is not None else saida,
                    "saida_s": saida if saida is not None else chegada,
                    "route_id": info[0],
                    "service_id": info[1],
                }

        inserir_em_lotes(db.horarios, horarios(), "horarios")

        print("shapes...")
        pontos = defaultdict(list)
        for r in ler(z, "shapes.txt"):
            pontos[r["shape_id"]].append(
                (
                    int(r["shape_pt_sequence"]),
                    float(r["shape_pt_lat"]),
                    float(r["shape_pt_lon"]),
                )
            )
        docs = [
            {
                "_id": p(sid),
                "fonte": fonte,
                "pontos": [[la, lo] for _, la, lo in sorted(pts)],
            }
            for sid, pts in pontos.items()
        ]
        for i in range(0, len(docs), 500):
            db.shapes.insert_many(docs[i : i + 500])
        print(f"  shapes: {len(docs):,}")

    print("índices...")
    db.viagens.create_index("route_id")
    db.shapes.create_index("fonte")
    db.horarios.create_index([("stop_id", 1), ("saida_s", 1)])
    db.horarios.create_index("trip_id")
    for nome in ("linhas", "paradas", "viagens", "horarios", "calendarios"):
        db[nome].create_index("fonte")
    db.linhas.create_index("busca")
    db.linhas.create_index([("tipo", 1), ("numero", 1)])
    db.paradas.create_index("busca")
    print("pronto.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    
    importar(sys.argv[1], sys.argv[2])
