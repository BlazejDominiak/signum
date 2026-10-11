"""Walidacja adresów usług AI i klasyfikacja lokalnego przetwarzania."""

from __future__ import annotations

import ipaddress
from urllib.parse import SplitResult, urlsplit, urlunsplit

from signum.i18n import tr


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
        raise EndpointValidationError(
            tr("core.network.the_address_is_too_long", service_name=service_name)
        )
    if any(character.isspace() for character in raw) or "\\" in raw:
        raise EndpointValidationError(
            tr(
                "core.network.the_address_cannot_contain_spaces_or_control",
                service_name=service_name,
            )
        )
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port  # wymusza walidację składni portu
    except ValueError as exc:
        raise EndpointValidationError(
            tr("core.network.invalid_address", service_name=service_name, error=exc)
        ) from exc

    if parsed.scheme not in {"http", "https"} or not host:
        raise EndpointValidationError(
            tr("core.network.the_address_must_be_a_complete_http", service_name=service_name)
        )
    if parsed.username is not None or parsed.password is not None:
        raise EndpointValidationError(
            tr("core.network.the_address_cannot_contain_a_username_or", service_name=service_name)
        )
    if parsed.query or parsed.fragment:
        raise EndpointValidationError(
            tr(
                "core.network.the_address_cannot_contain_query_parameters_or",
                service_name=service_name,
            )
        )
    if parsed.scheme == "http" and not _is_loopback_host(host):
        raise EndpointValidationError(
            tr("core.network.the_remote_address_must_use_https_because", service_name=service_name)
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


def processing_is_local(provider: str, api_url: str, model: str = "") -> bool:
    """Przetwarzanie na tym komputerze rozpoznajemy po rzeczywistym adresie API."""
    if provider == "ollama" and model.lower().endswith("cloud"):
        return False
    return provider in {"ollama", "openai", "anthropic", "vjev"} and (is_loopback_endpoint(api_url))


def _is_loopback_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
