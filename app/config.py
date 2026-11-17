from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "colosys_argos"

    jwt_secret: str = "troque-esta-chave"
    jwt_expire_min: int = 60 * 24 * 7  # 7 dias

    cors_origins: str = "http://localhost:5173"

    olhovivo_token: str = ""
    olhovivo_url: str = "http://api.olhovivo.sptrans.com.br/v2.1"

    trilhos_api_key: str = ""
    trilhos_url: str = "https://ccm.artesp.sp.gov.br/metroferroviario/api/status/"
    # O limite da API é 12 req/h por chave; 360 s = 10 req/h, com folga.
    trilhos_intervalo_s: int = 360


settings = Settings()
