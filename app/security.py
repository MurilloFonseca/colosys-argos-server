from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import db

bearer = HTTPBearer(auto_error=False)


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode()[:72], bcrypt.gensalt()).decode()


def confere_senha(senha: str, hash_: str) -> bool:
    return bcrypt.checkpw(senha.encode()[:72], hash_.encode())


def criar_token(usuario_id) -> str:
    exp: datetime = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_min)
    return jwt.encode(
        {"sub": str(usuario_id), "exp": exp}, settings.jwt_secret, "HS256"
    )


async def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    erro = HTTPException(401, "Não autenticado", headers={"WWW-Authenticate": "Bearer"})

    if not cred:
        raise erro

    try:
        payload: dict[str, Any] = jwt.decode(
            cred.credentials, settings.jwt_secret, algorithms=["HS256"]
        )
        usuario: dict[str, Any] | None = await db.usuarios.find_one(
            {"_id": ObjectId(payload["sub"])}
        )

    except Exception:
        raise erro

    if not usuario:
        raise erro

    return usuario
