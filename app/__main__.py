"""`uv run python -m app` - starts the server on this computer only (it spends your Anthropic credits)."""
import os
from pathlib import Path

import uvicorn


def load_dotenv(path: Path) -> None:
    """Reads KEY=VALUE lines from .env into the environment (existing variables win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8200")))
