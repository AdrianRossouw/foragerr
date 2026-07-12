"""Store-source integrations (m6-humble-source, area: sources — FRG-SRC-001..).

A generic store-source model — connection lifecycle, entitlement inventory,
review workflow — implemented for one store, Humble Bundle. Importing this
package pulls in the ORM models so the two ``sources`` / ``source_entitlements``
tables are mapped on ``Base.metadata`` (mirrors ``foragerr.downloads``).
"""

from __future__ import annotations

from foragerr.sources.models import SourceEntitlementRow, SourceRow

__all__ = ["SourceEntitlementRow", "SourceRow"]
