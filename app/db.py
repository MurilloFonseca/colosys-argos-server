from pymongo import AsyncMongoClient

from app.config import settings

client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
db = client[settings.mongo_db]


async def criar_indices() -> None:
    await db.usuarios.create_index("email", unique=True)
    await db.linhas.create_index("busca")
    await db.linhas.create_index([("tipo", 1), ("numero", 1)])
    await db.paradas.create_index("busca")
    await db.horarios.create_index([("stop_id", 1), ("saida_s", 1)])
    await db.horarios.create_index("trip_id")
    await db.favoritos.create_index("usuario_id")
    await db.favoritos.create_index(
        [("usuario_id", 1), ("linha_id", 1)],
        unique=True,
        partialFilterExpression={"tipo": "linha"},
    )
    await db.relatos.create_index([("criado_em", -1)])
    await db.relatos.create_index("linha_id")
    await db.avisos.create_index([("criado_em", -1)])
