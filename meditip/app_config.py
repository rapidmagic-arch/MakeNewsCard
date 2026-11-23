"""Local-only configuration loading. No API secrets are exposed to the web UI."""
from pathlib import Path
from dotenv import load_dotenv


def load_project_env(root):
    """Load project .env without overriding already-set environment variables."""
    return load_dotenv(dotenv_path=Path(root).resolve() / '.env', override=False)
