from __future__ import annotations

from typing import Any


class AttrDict(dict):
    """A dict subclass that supports attribute-style access (obj.key and obj['key'])
    and recursively wraps nested dicts/lists so callers can use either Python dict
    indexing or JS/TS dot notation.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for k, v in list(self.items()):
            super().__setitem__(k, _wrap(v))

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            # Support snake_case <-> camelCase fallback lookup
            camel = _snake_to_camel(name)
            if camel in self:
                return self[camel]
            snake = _camel_to_snake(name)
            if snake in self:
                return self[snake]
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self[name] = _wrap(value)

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, _wrap(value))


def _wrap(value: Any) -> Any:
    if isinstance(value, AttrDict):
        return value
    if isinstance(value, dict):
        return AttrDict(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def _snake_to_camel(name: str) -> str:
    if "_" not in name:
        return name
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
