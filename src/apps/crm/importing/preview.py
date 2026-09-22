from __future__ import annotations

from typing import Protocol

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .types import ImportPreviewBinding, StoredPreviewPayload


def preview_binding_for_job(job) -> ImportPreviewBinding:
    """Build the complete actor/tenant/schema/digest/expiry preview binding."""

    return ImportPreviewBinding(
        job_id=str(job.pk),
        business_id=job.business_id,
        actor_id=job.created_by_id,
        schema_version=job.schema_version,
        file_digest=job.file_digest,
        expires_at=job.expires_at,
    )


class PreviewPayloadStore(Protocol):
    """Block 3 storage boundary for authoritative, server-side normalized rows.

    Implementations must verify every field in ``ImportPreviewBinding`` on load and
    must not log payload contents. Browser sessions, URLs, and hidden form inputs are
    intentionally outside this interface.
    """

    def save(self, payload: StoredPreviewPayload) -> None: ...

    def load(self, binding: ImportPreviewBinding) -> StoredPreviewPayload | None: ...

    def delete(self, binding: ImportPreviewBinding) -> None: ...


class DatabasePreviewPayloadStore:
    """Persist trusted preview data on its already-bound ImportJob.

    Raw uploads never enter this store. Every operation resolves the complete
    binding so a job identifier alone cannot cross actor or tenant boundaries.
    """

    @staticmethod
    def _jobs_for_binding(binding: ImportPreviewBinding):
        from apps.crm.models import ImportJob

        return ImportJob.objects.filter(
            pk=binding.job_id,
            business_id=binding.business_id,
            created_by_id=binding.actor_id,
            schema_version=binding.schema_version,
            file_digest=binding.file_digest,
            expires_at=binding.expires_at,
        )

    @staticmethod
    def _serialized_binding(binding: ImportPreviewBinding) -> dict[str, object]:
        return {
            "job_id": str(binding.job_id),
            "business_id": binding.business_id,
            "actor_id": binding.actor_id,
            "schema_version": binding.schema_version,
            "file_digest": binding.file_digest,
            "expires_at": binding.expires_at.isoformat(),
        }

    def save(self, payload: StoredPreviewPayload) -> None:
        binding = payload.binding
        if binding.expires_at <= timezone.now():
            raise PermissionDenied("Import preview access denied.")
        updated = self._jobs_for_binding(binding).update(
            preview_payload={
                "binding": self._serialized_binding(binding),
                "normalized_rows": list(payload.normalized_rows),
                "metadata": payload.metadata,
            }
        )
        if updated != 1:
            raise PermissionDenied("Import preview access denied.")

    def load(self, binding: ImportPreviewBinding) -> StoredPreviewPayload | None:
        if binding.expires_at <= timezone.now():
            return None
        stored = (
            self._jobs_for_binding(binding)
            .values_list("preview_payload", flat=True)
            .first()
        )
        if not isinstance(stored, dict) or not stored:
            return None
        if stored.get("binding") != self._serialized_binding(binding):
            return None
        normalized_rows = stored.get("normalized_rows")
        metadata = stored.get("metadata")
        if not isinstance(normalized_rows, list) or not isinstance(metadata, dict):
            return None
        if not all(isinstance(row, dict) for row in normalized_rows):
            return None
        return StoredPreviewPayload(
            binding=binding,
            normalized_rows=tuple(normalized_rows),
            metadata=metadata,
        )

    def delete(self, binding: ImportPreviewBinding) -> None:
        self._jobs_for_binding(binding).update(preview_payload={})


database_preview_store = DatabasePreviewPayloadStore()
