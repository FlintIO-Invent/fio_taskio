from __future__ import annotations

from typing import Protocol

from .types import ImportPreviewBinding, StoredPreviewPayload


class PreviewPayloadStore(Protocol):
    """Block 3 storage boundary for authoritative, server-side normalized rows.

    Implementations must verify every field in ``ImportPreviewBinding`` on load and
    must not log payload contents. Browser sessions, URLs, and hidden form inputs are
    intentionally outside this interface.
    """

    def save(self, payload: StoredPreviewPayload) -> None: ...

    def load(self, binding: ImportPreviewBinding) -> StoredPreviewPayload | None: ...

    def delete(self, binding: ImportPreviewBinding) -> None: ...
