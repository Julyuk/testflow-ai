from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_provider: str = "openai"  # "openai" | "anthropic"
    llm_model: str = "gpt-4o"

    # Database
    database_url: str = "postgresql+psycopg://testflow:testflow@localhost:5432/testflow"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60

    # Azure DevOps
    azure_devops_org: str = ""
    azure_devops_pat: str = ""

    # App
    frontend_url: str = "http://localhost:5173"
    debug: bool = False


settings = Settings()
