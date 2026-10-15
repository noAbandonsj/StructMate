"""Backend-only connection parameters, independent of a provider or wire protocol."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, TypeAdapter, field_validator


class ModelConnection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    base_url: str = Field(min_length=1, max_length=2048, repr=False)
    model: str = Field(min_length=1, max_length=240)
    api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    expected_dimension: int | None = Field(default=None, ge=1, le=65536)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        try:
            parsed = TypeAdapter(HttpUrl).validate_python(value)
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError
        except ValueError as error:
            raise ValueError("模型地址须为 HTTP(S) 地址，身份凭据请单独配置") from error
        return str(parsed)
