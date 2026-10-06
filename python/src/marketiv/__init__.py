"""MarketIV — the financial impact graph, in Python.

    from marketiv import MarketIV
    mdx = MarketIV(api_key="…")
    for s in mdx.news(megatrend="ai-power", impact="indirect"):
        ...
"""

from __future__ import annotations

__version__ = "0.16.0"

from . import enums
from .client import GicsRef, MarketIV, MegatrendRef, StockRef
from .errors import (
    AuthError,
    BadRequestError,
    MarketIVError,
    NotFoundError,
    QuotaError,
    RateLimitError,
    ServerError,
)
from .models import Aspect, Company, Entity, GicsCode, Impact, MegatrendNode, MemberStock, Signal, StockNews

# Pre-rebrand names (MarketDX → MarketIV), kept as aliases.
MarketDX = MarketIV
MarketDXError = MarketIVError

__all__ = [
    "MarketIV",
    "MarketDX",
    "MegatrendRef",
    "GicsRef",
    "StockRef",
    "enums",
    # models
    "Signal",
    "StockNews",
    "Entity",
    "Impact",
    "Aspect",
    "MemberStock",
    "Company",
    "MegatrendNode",
    "GicsCode",
    # errors
    "MarketIVError",
    "MarketDXError",
    "AuthError",
    "QuotaError",
    "RateLimitError",
    "BadRequestError",
    "NotFoundError",
    "ServerError",
    "__version__",
]
