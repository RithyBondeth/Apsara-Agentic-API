from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )
    PROJECT_NAME: str = "Apsara Agentic CLI"
    DEBUG: bool = False
    AGENT_WORKSPACE_ROOT: str = "."
    AGENT_ENABLE_BASH_TOOL: bool = False
    AGENT_ALLOWED_COMMANDS: str = "pwd,ls,find,rg,cat,sed,head,tail,wc"
    AGENT_MAX_FILE_SIZE_BYTES: int = 1_000_000
    # Long enough for a real test suite or build. The previous 30s meant the
    # agent could enable bash and still be unable to run the thing that proves
    # its work.
    AGENT_BASH_TIMEOUT_SECONDS: int = 120

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
