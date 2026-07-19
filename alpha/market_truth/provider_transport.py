from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message


@dataclass(frozen=True, slots=True)
class ReadOnlyHttpResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class MarketTruthNetworkError(RuntimeError):
    pass


class ReadOnlyProviderTransport:
    """MTE-owned GET transport; downstream modules never open provider sockets."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: int,
    ) -> ReadOnlyHttpResponse:
        request = urllib.request.Request(
            url,
            headers=dict(headers),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return ReadOnlyHttpResponse(
                    status=int(response.status),
                    headers=_header_pairs(response.headers),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return ReadOnlyHttpResponse(
                status=int(error.code),
                headers=_header_pairs(error.headers),
                body=error.read(),
            )
        except urllib.error.URLError as error:
            raise MarketTruthNetworkError(
                f"provider request failed with {error.__class__.__name__}"
            ) from None


def _header_pairs(headers: Message | None) -> tuple[tuple[str, str], ...]:
    if headers is None:
        return ()
    return tuple((str(key), str(value)) for key, value in headers.items())


__all__ = [
    "MarketTruthNetworkError",
    "ReadOnlyHttpResponse",
    "ReadOnlyProviderTransport",
]
