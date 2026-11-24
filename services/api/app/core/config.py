from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    postgres_host: str = Field(default="postgres", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="fincrime", validation_alias="POSTGRES_DB")
    postgres_schema: str = Field(default="app", validation_alias="POSTGRES_APP_SCHEMA")

    # Non-superuser role services/api connects as -- never the bootstrap
    # role (POSTGRES_APP_USER) used for image init/migrations. See
    # docs/pre-production-security-todo.md.
    postgres_runtime_user: str = Field(default="app_runtime", validation_alias="POSTGRES_APP_RUNTIME_USER")
    postgres_runtime_password: str = Field(validation_alias="POSTGRES_APP_RUNTIME_PASSWORD")

    api_jwt_audience: str = Field(default="fincrime-api", validation_alias="API_JWT_AUDIENCE")

    # Real OIDC provider (Keycloak, Sprint 4 -- see docs/sprint-4-identity-and-authz.md).
    # oidc_issuer_url must match the `iss` claim Keycloak actually issues
    # exactly (fixed via KC_HOSTNAME, not derived from how a caller reached
    # it) -- see infra/keycloak/realm-export.json.
    oidc_issuer_url: str = Field(validation_alias="OIDC_ISSUER_URL")
    oidc_client_id: str = Field(default="fincrime-api", validation_alias="OIDC_CLIENT_ID")

    # Deliberately a SEPARATE setting from oidc_issuer_url, not derived from
    # it: the issuer is a claim-matching *string* (must equal what Keycloak
    # embeds in `iss`, always the in-network host:port), while this is a
    # *network address* the validating process must actually be able to
    # reach. They coincide inside Docker but diverge when the API runs
    # in-process on the host (e.g. pytest via ASGITransport) -- see
    # tests/conftest.py's OIDC_JWKS_URL override.
    oidc_jwks_url_override: str | None = Field(default=None, validation_alias="OIDC_JWKS_URL")

    @property
    def oidc_jwks_url(self) -> str:
        return self.oidc_jwks_url_override or f"{self.oidc_issuer_url}/protocol/openid-connect/certs"

    # Placeholder service-to-service credential until a real service-account
    # OIDC client is adopted for n8n -> API calls too.
    service_token: str = Field(validation_alias="N8N_API_SERVICE_TOKEN")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_runtime_user}:{self.postgres_runtime_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
