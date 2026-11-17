from typing import Literal, Self

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegistroIn(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    email: EmailStr
    senha: str = Field(min_length=6, max_length=72)


class LoginIn(BaseModel):
    email: EmailStr
    senha: str


class UsuarioOut(BaseModel):
    id: str
    nome: str
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut


# Mesmos campos do FormularioRelato.jsx
class Avaliacoes(BaseModel):
    conservacao: int = Field(0, ge=0, le=5)
    atendimento: int = Field(0, ge=0, le=5)
    seguranca: int = Field(0, ge=0, le=5)
    limpeza: int = Field(0, ge=0, le=5)
    arCondicionado: int = Field(0, ge=0, le=5)
    acessibilidade: int = Field(0, ge=0, le=5)
    equipe: int = Field(0, ge=0, le=5)


class RelatoIn(BaseModel):
    transporte: Literal["Metrô", "Trem", "Ônibus"]
    linha_id: str | None = None  # id vindo de GET /linhas
    avaliacoes: Avaliacoes
    comentario: str = Field("", max_length=1000)

    @model_validator(mode="after")
    def tem_alguma_nota(self) -> Self:
        if not any(self.avaliacoes.model_dump().values()):
            raise ValueError("Informe pelo menos uma avaliação")

        return self


class FavLinhaIn(BaseModel):
    linha_id: str


class FavTrajetoIn(BaseModel):
    origem: str = Field(min_length=1, max_length=120)
    destino: str = Field(min_length=1, max_length=120)
    transporte: str | None = None
    tempo: str | None = None
