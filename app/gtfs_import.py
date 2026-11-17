"""Importa um GTFS (.zip) para o MongoDB.

Uso:  python -m app.gtfs_import <fonte> <arquivo.zip>
Ex.:  python -m app.gtfs_import sptrans gtfs_sptrans.zip
      python -m app.gtfs_import artesp  gtfs_artesp.zip

`fonte` é só um rótulo: vira prefixo dos ids (ex.: "sptrans:3766-10") para que
feeds diferentes não colidam. Reimportar a mesma fonte substitui os dados dela.

NÃO guardamos horários (stop_times). Em vez disso, cada linha vira "padrões":
a sequência de paradas de um sentido + minutos médios desde a 1ª parada.
Milhares de viagens iguais viram um único documento.
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


def segundos(hora):
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
    if lote:
        colecao.insert_many(lote, ordered=False)
        total += len(lote)
    print(f"  {nome}: {total:,}")


# --------------------------------------------------------------- padrões
class NaoAgrupado(Exception):
    pass


def agrupa_sequencial(linhas):
    """Agrupa stop_times por viagem lendo em sequência (usa pouca memória).
    Exige o arquivo agrupado por trip_id, o que é o comum em GTFS."""
    atual, buf, vistas = None, [], set()
    for r in linhas:
        t = r["trip_id"]
        if t != atual:
            if buf:
                yield atual, buf
                vistas.add(atual)
            if t in vistas:
                raise NaoAgrupado
            atual, buf = t, []
        buf.append(r)
    if buf:
        yield atual, buf


def agrupa_em_memoria(linhas):
    grupos = defaultdict(list)
    for r in linhas:
        grupos[r["trip_id"]].append(r)
    yield from grupos.items()


def tempos_da_viagem(rs):
    """Lista de tempos (s) por parada, preenchendo buracos (paradas sem horário)."""
    ts = []
    for r in rs:
        t = segundos(r.get("arrival_time"))
        ts.append(t if t is not None else segundos(r.get("departure_time")))
    conhecidos = [t for t in ts if t is not None]
    if not conhecidos:
        return None
    ultimo = conhecidos[0]
    for i, t in enumerate(ts):
        ts[i] = ultimo = t if t is not None else ultimo
    return ts


def monta_padroes(z, info_viagem, p):
    """{(route_id, sentido, paradas): {...}} somando minutos de todas as viagens iguais."""
    for agrupador in (agrupa_sequencial, agrupa_em_memoria):
        acum = {}
        try:
            for trip_id, rs in agrupador(ler(z, "stop_times.txt")):
                info = info_viagem.get(trip_id)
                if not info:
                    continue
                rs.sort(key=lambda r: int(r["stop_sequence"]))
                ts = tempos_da_viagem(rs)
                if not ts:
                    continue
                paradas = tuple(p(r["stop_id"]) for r in rs)
                offsets = [t - ts[0] for t in ts]
                chave = (info["route_id"], info["sentido"], paradas)
                a = acum.get(chave)
                if a is None:
                    acum[chave] = {
                        "n": 1,
                        "soma": offsets,
                        "destino": info["destino"],
                        "shape_id": info["shape_id"],
                    }
                else:
                    assert type(a["n"]) is int 
                    assert type(a["soma"]) is list
                    a["n"] += 1
                    a["soma"] = [x + y for x, y in zip(a["soma"], offsets)]
            return acum
        except NaoAgrupado:
            print(
                "  stop_times.txt não está agrupado por viagem; usando modo em memória (mais lento)..."
            )
    return {}


# ------------------------------------------------------------- importação
def importar(fonte: str, caminho: str):
    db = MongoClient(settings.mongo_url)[settings.mongo_db]
    p = lambda i: f"{fonte}:{i}"  # prefixo

    # Coleções de versões anteriores (guardavam horários): não são mais usadas.
    for antiga in ("horarios", "viagens", "calendarios"):
        db.drop_collection(antiga)
    for nome in ("linhas", "paradas", "padroes", "shapes", "tarifas", "regras_tarifa"):
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
                    "zona": r.get("zone_id") or None,  # usado pelas regras de tarifa
                    "busca": normaliza(r.get("stop_name", "")),
                }

        inserir_em_lotes(db.paradas, paradas(), "paradas")

        print("padrões de viagem (a partir de stop_times)... pode demorar")
        info_viagem = {
            r["trip_id"]: {
                "route_id": p(r["route_id"]),
                "sentido": r.get("direction_id", ""),
                "destino": r.get("trip_headsign", ""),
                "shape_id": p(r["shape_id"]) if r.get("shape_id") else None,
            }
            for r in ler(z, "trips.txt")
        }
        acum = monta_padroes(z, info_viagem, p)
        docs = (
            {
                "fonte": fonte,
                "route_id": rota,
                "sentido": sentido,
                "destino": a["destino"],
                "shape_id": a["shape_id"],
                "n_viagens": a["n"],
                "paradas": list(paradas_),
                "minutos": [round(x / a["n"] / 60) for x in a["soma"]],
            }
            for (rota, sentido, paradas_), a in acum.items()
        )
        inserir_em_lotes(db.padroes, docs, "padrões")
        del acum, info_viagem

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
        shapes = [
            {
                "_id": p(sid),
                "fonte": fonte,
                "pontos": [[la, lo] for _, la, lo in sorted(pts)],
            }
            for sid, pts in pontos.items()
        ]
        for i in range(0, len(shapes), 500):
            db.shapes.insert_many(shapes[i : i + 500])
        print(f"  shapes: {len(shapes):,}")

        print("tarifas...")

        def numero(txt, tipo=float):
            try:
                return tipo(txt.replace(",", "."))
            except AttributeError, ValueError:
                return None

        tarifas = [
            {
                "_id": p(r["fare_id"]),
                "fonte": fonte,
                "preco": numero(r.get("price")),
                "moeda": r.get("currency_type") or "BRL",
                "pagamento": r.get(
                    "payment_method"
                ),  # "0" = a bordo, "1" = antes de embarcar
                "baldeacoes": numero(
                    r.get("transfers"), int
                ),  # None = ilimitadas (ou não informado)
                "duracao_baldeacao_s": numero(r.get("transfer_duration"), int),
                "operadora": agencias.get(r.get("agency_id", ""), unica),
            }
            for r in ler(z, "fare_attributes.txt")
        ]
        if tarifas:
            db.tarifas.insert_many(tarifas)
        print(f"  tarifas: {len(tarifas):,}")
        regras = (
            {
                "fonte": fonte,
                "fare_id": p(r["fare_id"]),
                "route_id": p(r["route_id"]) if r.get("route_id") else None,
                "origem_zona": r.get("origin_id") or None,
                "destino_zona": r.get("destination_id") or None,
                "contem_zona": r.get("contains_id") or None,
            }
            for r in ler(z, "fare_rules.txt")
        )
        inserir_em_lotes(db.regras_tarifa, regras, "regras de tarifa")

    print("índices...")
    for nome in ("linhas", "paradas", "padroes", "shapes", "tarifas", "regras_tarifa"):
        db[nome].create_index("fonte")
    db.linhas.create_index("busca")
    db.linhas.create_index([("tipo", 1), ("numero", 1)])
    db.paradas.create_index("busca")
    db.padroes.create_index("route_id")
    db.padroes.create_index("paradas")
    db.regras_tarifa.create_index("route_id")
    db.regras_tarifa.create_index("fare_id")
    print("pronto.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    importar(sys.argv[1], sys.argv[2])
