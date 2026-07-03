from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Project Alpha"
    environment: str = "development"

    class Config:
        env_file = ".env"