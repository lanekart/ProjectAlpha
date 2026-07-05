from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Global application configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
    )

    app_name: str = "Project Alpha"
    environment: str = "development"

    project_root: Path = Path.cwd()

    data_dir: Path = Path("data")
    raw_data_dir: Path = Path("data/raw")
    extracted_data_dir: Path = Path("data/extracted")

    database_path: Path = Path("data/ingestion.duckdb")


settings = Settings()
