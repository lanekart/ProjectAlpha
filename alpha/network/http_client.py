from __future__ import annotations

from typing import Any

import requests


class HTTPClient:
    """
    Thin wrapper around requests.Session.

    Responsibilities
    ----------------
    - Maintain a persistent HTTP session.
    - Provide sensible browser headers.
    - Centralize all outbound HTTP traffic.

    Retry logic, telemetry and rate limiting will be added later.
    """

    def __init__(self) -> None:
        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/138.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.session.get(url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        return self.session.head(url, **kwargs)
