from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://ledger:ledger@localhost:5432/ledger"
    db_pool_min_size: int = 2
    db_pool_max_size: int = 20

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

