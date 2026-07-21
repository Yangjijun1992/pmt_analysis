from __future__ import annotations

import urllib.request
import json


GITHUB_API_URL = "https://api.github.com/user"

ALLOWED_USER = "Yangjijun1992"


class AuthenticationError(Exception):
    """Raised when GitHub authentication fails."""


def verify_github_user(github_user: str, github_token: str) -> bool:
    if github_user != ALLOWED_USER:
        raise AuthenticationError(
            f"User '{github_user}' is not authorized to modify the database. "
            f"Only '{ALLOWED_USER}' has write permission."
        )

    req = urllib.request.Request(GITHUB_API_URL)
    req.add_header("Authorization", f"token {github_token}")
    req.add_header("User-Agent", "pmt-analysis")
    req.add_header("Accept", "application/vnd.github+json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthenticationError(
                "GitHub token is invalid or expired. Please provide a valid classic token."
            )
        raise AuthenticationError(f"GitHub API error (HTTP {e.code}): {e.reason}")
    except Exception as e:
        raise AuthenticationError(f"Failed to contact GitHub API: {e}")

    login = data.get("login", "")
    if login != ALLOWED_USER:
        raise AuthenticationError(
            f"Token belongs to '{login}', but only '{ALLOWED_USER}' "
            f"is authorized to modify the database."
        )

    return True
