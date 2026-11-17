from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from ..db import db
from ..schemas import LoginIn, RegistroIn, TokenOut, UsuarioOut
from ..security import confere_senha, criar_token, hash_senha, usuario_atual

router = APIRouter(prefix="/auth", tags=["auth"])


def _usuario_out(u: dict[str, Any]) -> UsuarioOut:
    return UsuarioOut(id=str(u["_id"]), nome=u["nome"], email=u["email"])


def _resposta(u: dict[str, Any]) -> TokenOut:
    return TokenOut(access_token=criar_token(u["_id"]), usuario=_usuario_out(u))


@router.post("/registro", response_model=TokenOut, status_code=201)
async def registro(dados: RegistroIn) -> TokenOut:
    doc: dict[str, Any] = {
        "nome": dados.nome.strip(),
        "email": dados.email.lower(),
        "senha_hash": hash_senha(dados.senha),
        "criado_em": datetime.now(UTC),
    }

    try:
        doc["_id"] = (await db.usuarios.insert_one(doc)).inserted_id

    except DuplicateKeyError:
        raise HTTPException(409, "E-mail já cadastrado")

    return _resposta(doc)


@router.post("/login", response_model=TokenOut)
async def login(dados: LoginIn) -> TokenOut:
    u: dict[str, Any] | None = await db.usuarios.find_one(
        {"email": dados.email.lower()}
    )

    if not u or not confere_senha(dados.senha, u["senha_hash"]):
        raise HTTPException(401, "E-mail ou senha inválidos")

    return _resposta(u)


@router.get("/me", response_model=UsuarioOut)
async def me(usuario=Depends(usuario_atual)) -> UsuarioOut:
    return _usuario_out(usuario)
