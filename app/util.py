import unicodedata
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")


def normaliza(texto: str) -> str:
    """minúsculas e sem acento, para busca ('Sé' casa com 'se')."""
    sem_acento: str = unicodedata.normalize("NFD", texto or "")
    sem_acento: str = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return sem_acento.lower().strip()
