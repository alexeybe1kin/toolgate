import os
import re
import uuid

from dotenv import dotenv_values, set_key, unset_key

from toolgate.core.paths import ENV_PATH

_CONTROL_KEYS = {"TOOLGATE_ADMIN_KEY"}
_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _load() -> dict:
    if not ENV_PATH.exists():
        return {}
    return {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}


def get_key(placeholder: str) -> str:
    """Return the real value for a vault placeholder. Never exposed to callers via list_placeholders()."""
    value = _load().get(placeholder) or os.environ.get(placeholder)
    if not value:
        raise KeyError(f"{placeholder} is not set in .env")
    return value


def list_placeholders() -> list[str]:
    """Return placeholder names only. Values are never returned by this function."""
    return sorted(k for k in _load() if k not in _CONTROL_KEYS)


def set_secret(name: str, value: str, *, allow_existing: bool = True) -> None:
    if name in _CONTROL_KEYS:
        raise ValueError(f"{name} is an internal control key, not a vault secret")
    if not _NAME_PATTERN.match(name):
        raise ValueError("Key name must be SCREAMING_SNAKE_CASE (e.g. GITHUB_TOKEN)")
    if not allow_existing and name in _load():
        raise ValueError(f"{name} already exists")

    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), name, value, quote_mode="never")


def delete_secret(name: str) -> None:
    if name in _CONTROL_KEYS:
        raise ValueError(f"{name} is an internal control key, cannot be deleted here")
    if name not in _load():
        raise KeyError(name)
    unset_key(str(ENV_PATH), name)


def get_control_key(name: str) -> str | None:
    """Read the owner-only admin key, which is never a vault placeholder."""
    if name != "TOOLGATE_ADMIN_KEY":
        return None
    return _load().get(name) or os.environ.get(name)


def ensure_control_keys() -> dict:
    """Generate TOOLGATE_ADMIN_KEY on first run if missing and persist it.

    Returns the key only when it was freshly generated.
    """
    if not ENV_PATH.exists():
        ENV_PATH.touch()

    values = _load()
    generated = {}
    for name in ("TOOLGATE_ADMIN_KEY",):
        if values.get(name):
            continue
        configured = os.environ.get(name, "").strip()
        if configured:
            set_key(str(ENV_PATH), name, configured, quote_mode="never")
            continue
        new_value = uuid.uuid4().hex
        set_key(str(ENV_PATH), name, new_value, quote_mode="never")
        os.environ[name] = new_value
        generated[name] = new_value

    return generated


def rotate_control_key(name: str) -> str:
    if name != "TOOLGATE_ADMIN_KEY":
        raise ValueError(f"Cannot rotate {name}")
    new_value = uuid.uuid4().hex
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), name, new_value, quote_mode="never")
    os.environ[name] = new_value
    return new_value
