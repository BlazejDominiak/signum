"""Walidacja adresów usług AI i klasyfikacja lokalnego przetwarzania."""

from __future__ import annotations

import ipaddress
from urllib.parse import SplitResult, urlsplit, urlunsplit


class EndpointValidationError(ValueError):
    """Adres usługi AI jest niepoprawny albo używa niebezpiecznego transportu."""


def normalize_ai_endpoint(value: str, default: str, service_name: str) -> str:
    """Normalizuje endpoint i wymaga HTTPS poza adresem loopback.

    Nieszyfrowane HTTP jest dopuszczalne wyłącznie dla ``localhost`` oraz
    adresów IP pętli zwrotnej. Host z sieci LAN również oznacza transfer poza
    komputer i musi korzystać z HTTPS.
    """
    raw = (value or default).strip().rstrip("/")
    if len(raw) > 2048:
        raise EndpointValidationError(f"Adres {service_name} jest zbyt długi.")
    if any(character.isspace() for character in raw) or "\\" in raw:
        raise EndpointValidationError(
            f"Adres {service_name} nie może zawierać spacji ani znaków sterujących."
        )
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port  # wymusza walidację składni portu
    except ValueError as exc:
        raise EndpointValidationError(f"Niepoprawny adres {service_name}: {exc}") from exc

    if parsed.scheme not in {"http", "https"} or not host:
        raise EndpointValidationError(
            f"Adres {service_name} musi być pełnym adresem HTTP lub HTTPS."
        )
    if parsed.username is not None or parsed.password is not None:
        raise EndpointValidationError(
            f"Adres {service_name} nie może zawierać nazwy użytkownika ani hasła."
        )
    if parsed.query or parsed.fragment:
        raise EndpointValidationError(
            f"Adres {service_name} nie może zawierać parametrów ani fragmentu."
        )
    if parsed.scheme == "http" and not _is_loopback_host(host):
        raise EndpointValidationError(
            f"Zdalny adres {service_name} musi używać HTTPS, ponieważ otrzymuje "
            "treść dokumentów i może otrzymywać klucz API."
        )

    hostname = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = f"{hostname}:{port}" if port is not None else hostname
    normalized = SplitResult(parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", "")
    return urlunsplit(normalized)


def is_loopback_endpoint(value: str) -> bool:
    """Czy endpoint jednoznacznie wskazuje ten sam komputer."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
    except ValueError:
        return False
    return bool(host and _is_loopback_host(host))


def processing_is_local(provider: str, api_url: str) -> bool:
    """Przetwarzanie na tym komputerze rozpoznajemy po rzeczywistym adresie API."""
    return provider in {"ollama", "openai", "anthropic", "vjev"} and (
        is_loopback_endpoint(api_url)
    )


def _is_loopback_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
