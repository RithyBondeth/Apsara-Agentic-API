import json
import os
from pathlib import Path
from typing import Optional

CREDENTIALS_PATH = Path.home() / ".apsara" / "credentials.json"

def get_auth_token() -> Optional[str]:
    """Retrieve the stored Apsara access token."""
    if not CREDENTIALS_PATH.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        return data.get("access_token")
    except Exception:
        return None

def save_auth_token(token: str) -> None:
    """Securely save the Apsara access token."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"access_token": token}
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Set permissions to read/write only by owner
    CREDENTIALS_PATH.chmod(0o600)

def clear_auth_token() -> None:
    """Remove the stored Apsara access token."""
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()

def is_authenticated() -> bool:
    """Check if a valid token exists."""
    return get_auth_token() is not None
