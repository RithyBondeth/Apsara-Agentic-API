from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "FastAPI Project"
    DEBUG: bool = False
    SQLALCHEMY_DATABASE_URI: str = "postgresql://user:password@localhost:5432/dbname"
    AGENT_WORKSPACE_ROOT: str = "."
    AGENT_ENABLE_BASH_TOOL: bool = False
    AGENT_ALLOWED_COMMANDS: str = "pwd,ls,find,rg,cat,sed,head,tail,wc"
    AGENT_MAX_FILE_SIZE_BYTES: int = 1_000_000

    @property
    def agent_workspace_root_path(self) -> Path:
        return Path(self.AGENT_WORKSPACE_ROOT).expanduser().resolve()

    @property
    def agent_allowed_commands(self) -> set[str]:
        return {
            command.strip()
            for command in self.AGENT_ALLOWED_COMMANDS.split(",")
            if command.strip()
        }


settings = Settings()
