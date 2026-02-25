import os
from pathlib import Path

from dotenv import load_dotenv

try:
    from .runtime_config import deep_get, load_settings, to_str
except ImportError:  # pragma: no cover - script-style import fallback
    from runtime_config import deep_get, load_settings, to_str

# Always load env from this package directory, regardless of process cwd.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)


def _normalize_env(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().strip('"').strip("'")


_SETTINGS = load_settings()

OPENROUTER_API_KEY = _normalize_env(
    os.getenv("OPENROUTER_API_KEY")
    or to_str(deep_get(_SETTINGS, "models.openrouter_api_key"), default=None)
)

OPENROUTER_SERVICE = os.getenv(
    "OPENROUTER_SERVICE",
    to_str(deep_get(_SETTINGS, "models.openrouter_service"), default="openrouter_openai"),
)
OPENROUTER_MODEL_NAME = os.getenv(
    "OPENROUTER_MODEL_NAME",
    to_str(deep_get(_SETTINGS, "models.openrouter_model_name"), default="openai/gpt-4.1-mini"),
)

AMEM_EMBEDDING_MODEL_NAME = to_str(
    deep_get(_SETTINGS, "models.amem_embedding_model_name"),
    default="all-MiniLM-L6-v2",
)
GAM_DENSE_RETRIEVER_MODEL_NAME = to_str(
    deep_get(_SETTINGS, "models.gam_dense_retriever_model_name"),
    default="BAAI/bge-m3",
)
