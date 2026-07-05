"""Generic, provider-agnostic infrastructure shared by every remote provider.

The one member today is the escalating failure back-off ladder
(:mod:`foragerr.providers.backoff`, FRG-IDX-010 / FRG-NFR-005). It is
deliberately generic over ``(provider_type, provider_id)`` so change 5's
download clients and DDL provider reuse it unmodified — they add rows, never a
schema change (design decision 6).
"""

from foragerr.providers.backoff import (
    LADDER,
    MAX_LEVEL,
    PROVIDER_DDL,
    PROVIDER_DOWNLOAD_CLIENT,
    PROVIDER_INDEXER,
    BackoffStatus,
    ProviderBackoff,
    ProviderBackoffRow,
)

__all__ = [
    "LADDER",
    "MAX_LEVEL",
    "PROVIDER_DDL",
    "PROVIDER_DOWNLOAD_CLIENT",
    "PROVIDER_INDEXER",
    "BackoffStatus",
    "ProviderBackoff",
    "ProviderBackoffRow",
]
