"""Shared integer-parsing and pagination helpers.

Replaces the many local ``_parse_int`` / ``_parse_int_arg`` definitions
scattered across route modules.
"""
from __future__ import annotations

from flask import request


def parse_int(value, default=None):
    """Convert *value* to ``int``, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_int_arg(name: str, default=None):
    """Read a query-string argument and return it as ``int``."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return value
