from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .._types import AttrDict
from ..errors import TradingViewError
from .request import Credentials, HttpOptions, request

AuthorizedUser = AttrDict
AuthorizedUserOrder = str
PinePermissionOptions = dict[str, Any]


def _format_iso(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class PinePermissionManager:
    """Manages who can use an invite-only Pine script you own."""

    def __init__(self, pine_id: str, options: dict[str, Any] | None = None, **kwargs: Any) -> None:
        opts = {**(options or {}), **kwargs}
        if not pine_id:
            raise TradingViewError("INVALID_ARGUMENT", "A Pine ID is required")
        creds = opts.get("credentials")
        if not isinstance(creds, dict) or not creds.get("session"):
            raise TradingViewError("INVALID_ARGUMENT", "A session cookie is required")
        if not creds.get("signature"):
            raise TradingViewError("INVALID_ARGUMENT", "A session signature is required")
        self.pine_id: str = pine_id
        self.pineId: str = pine_id
        self._credentials = creds
        self._options = {
            "fetch": opts.get("fetch"),
            "signal": opts.get("signal"),
            "headers": opts.get("headers"),
        }

    async def _post(
        self,
        path: str,
        form: dict[str, str | None],
        query: dict[str, Any] | None = None,
    ) -> Any:
        res = await request(
            f"https://www.tradingview.com/pine_perm/{path}",
            {
                "method": "POST",
                "query": query,
                "form": {"pine_id": self.pine_id, **form},
                "credentials": self._credentials,
                "headers": {"origin": "https://www.tradingview.com"},
            },
            self._options,
        )
        status = res.status
        data = res.data
        if status >= 400:
            detail = (data.get("detail") if isinstance(data, dict) else None) or "Wrong credentials or pineId"
            raise TradingViewError(
                "NOT_FOUND" if status == 404 else "HTTP_ERROR",
                str(detail),
                {"details": data},
            )
        return data

    async def get_users(self, limit: int = 10, order: str = "-created") -> list[AuthorizedUser]:
        """Lists authorized users."""
        data = await self._post("list_users/", {}, {"limit": limit, "order_by": order})
        results = data.get("results") if isinstance(data, dict) else None
        return [AttrDict(u) for u in results] if isinstance(results, list) else []

    getUsers = get_users

    async def add_user(self, username: str, expiration: datetime | str | None = None) -> str:
        """Authorizes a user, optionally until a date."""
        data = await self._post("add/", {"username_recip": username, "expiration": _format_iso(expiration)})
        return str(data.get("status")) if isinstance(data, dict) and data.get("status") is not None else ""

    addUser = add_user

    async def modify_expiration(self, username: str, expiration: datetime | str | None = None) -> str:
        """Changes (or removes, without date) the expiration of a user's access."""
        data = await self._post(
            "modify_user_expiration/",
            {"username_recip": username, "expiration": _format_iso(expiration)},
        )
        return str(data.get("status")) if isinstance(data, dict) and data.get("status") is not None else ""

    modifyExpiration = modify_expiration

    async def remove_user(self, username: str) -> str:
        """Revokes a user's access."""
        data = await self._post("remove/", {"username_recip": username})
        return str(data.get("status")) if isinstance(data, dict) and data.get("status") is not None else ""

    removeUser = remove_user
