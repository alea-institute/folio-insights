"""Bring-your-own-key credentials (R2, KTD3).

A credential is a value handed in by the person running the work, never an ambient server
secret:

* the CLI builds :class:`Credentials` from the invoking user's own environment
  (:meth:`Credentials.from_env`);
* the API takes a key per request and gives the job an in-memory handle
  (``folio_insights.jobs.secrets``).

:class:`SecretKey` exists so a key cannot leak by accident. Its ``repr``/``str`` are redacted,
it refuses to be pickled, copied into JSON or compared by value, and the raw value is reachable
only through :meth:`SecretKey.reveal`, which the provider adapter calls at the moment it builds
an SDK client. Nothing in the port logs, persists or formats a revealed value.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from folio_insights.llm.errors import MissingCredentialsError

_REDACTED = "***"


class SecretKey:
    """An opaque API key. Redacted in every textual form; unpicklable; reveal-on-use only."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("a SecretKey needs a non-empty string value")
        object.__setattr__(self, "_value", value.strip())

    def reveal(self) -> str:
        """Return the raw key. Call only where an SDK client is constructed."""
        return self._value

    def __setattr__(self, name: str, value: Any) -> None:  # immutability
        raise AttributeError("SecretKey is immutable")

    def __repr__(self) -> str:
        return f"SecretKey('{_REDACTED}')"

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        return repr(self)

    def __reduce__(self) -> Any:
        raise TypeError("SecretKey cannot be pickled or serialized")

    def __reduce_ex__(self, protocol: Any) -> Any:
        raise TypeError("SecretKey cannot be pickled or serialized")

    def __copy__(self) -> SecretKey:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> SecretKey:
        return self

    def __bool__(self) -> bool:
        return True

    def __eq__(self, other: object) -> bool:
        # Identity only: value comparison would make keys usable as dict keys by value and invite
        # equality checks against user input in logs/tests.
        return self is other

    def __hash__(self) -> int:
        return id(self)


# Environment variables the CLI reads for each provider, in priority order. Only the CLI calls
# ``Credentials.from_env``: it is the invoking user's own key.
PROVIDER_KEY_ENV: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "ollama": ("OLLAMA_API_KEY",),
}


class Credentials:
    """Per-provider :class:`SecretKey` handles for one user, run or request."""

    __slots__ = ("_keys",)

    def __init__(self, keys: Mapping[str, SecretKey | str] | None = None) -> None:
        normalized: dict[str, SecretKey] = {}
        for provider, key in (keys or {}).items():
            if key is None or key == "":
                continue
            normalized[provider.strip().lower()] = key if isinstance(key, SecretKey) else SecretKey(key)
        object.__setattr__(self, "_keys", normalized)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Credentials is immutable")

    @classmethod
    def empty(cls) -> Credentials:
        return cls()

    @classmethod
    def single(cls, provider: str, key: SecretKey | str) -> Credentials:
        return cls({provider: key})

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Credentials:
        """The invoking user's own keys, for the CLI. Server code must never call this."""
        env = os.environ if environ is None else environ
        keys: dict[str, SecretKey] = {}
        for provider, names in PROVIDER_KEY_ENV.items():
            for name in names:
                value = (env.get(name) or "").strip()
                if value:
                    keys[provider] = SecretKey(value)
                    break
        return cls(keys)

    def get(self, provider: str) -> SecretKey | None:
        return self._keys.get(provider.strip().lower())

    def require(self, provider: str, *, requires_key: bool = True) -> SecretKey | None:
        """Return the provider's key, or raise :class:`MissingCredentialsError` if it needs one."""
        key = self.get(provider)
        if key is None and requires_key:
            names = " or ".join(PROVIDER_KEY_ENV.get(provider, ()))
            hint = f" (CLI: set {names})" if names else ""
            raise MissingCredentialsError(
                f"no API key supplied for LLM provider {provider!r}{hint}",
                provider=provider,
            )
        return key

    def providers(self) -> list[str]:
        return sorted(self._keys)

    def secrets(self) -> list[SecretKey]:
        return list(self._keys.values())

    def merged(self, other: Credentials) -> Credentials:
        """A new set where ``other``'s keys win."""
        combined: dict[str, SecretKey] = dict(self._keys)
        combined.update(other._keys)
        return Credentials(combined)

    def __bool__(self) -> bool:
        return bool(self._keys)

    def __repr__(self) -> str:
        return f"Credentials(providers={self.providers()!r})"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("Credentials cannot be pickled or serialized")

    def __reduce_ex__(self, protocol: Any) -> Any:
        raise TypeError("Credentials cannot be pickled or serialized")

    def __copy__(self) -> Credentials:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Credentials:
        return self


# Masked-key echoes ("sk-abc*****wxyz") and bare key-shaped tokens. Provider error bodies can
# contain either; the port scrubs both before an error message leaves it.
_MASKED_TOKEN = re.compile(r"[A-Za-z0-9_\-]*\*{3,}[A-Za-z0-9_\-]*")
_KEY_SHAPED = re.compile(r"\b(?:sk|pk|rk|key|AIza)[-_A-Za-z0-9]{12,}\b")


def scrub(text: str, secrets: list[SecretKey] | tuple[SecretKey, ...] = ()) -> str:
    """Remove every known secret, any masked-key echo and key-shaped tokens from ``text``."""
    out = str(text)
    for secret in secrets:
        value = secret.reveal()
        if value:
            out = out.replace(value, _REDACTED)
            # Provider echoes often keep a prefix/suffix of the key; drop those fragments too.
            for fragment in (value[:8], value[-6:]):
                if len(fragment) >= 6:
                    out = out.replace(fragment, _REDACTED)
    out = _MASKED_TOKEN.sub(_REDACTED, out)
    out = _KEY_SHAPED.sub(_REDACTED, out)
    return out
