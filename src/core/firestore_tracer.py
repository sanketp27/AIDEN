from __future__ import annotations

import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.tracer import AgentTrace

log = structlog.get_logger()

_COLLECTION = "agent_traces"  # Firestore top-level collection


async def persist_trace_firestore(trace: "AgentTrace") -> bool:
    """
    Persist an AgentTrace to Cloud Firestore.

    Returns True on success, False if Firestore is not configured or write fails.
    The caller should not await failure — this is best-effort.
    """
    try:
        from src.core.config import settings

        # Firestore requires a GCP project — skip gracefully in local dev
        project = settings.GOOGLE_CLOUD_PROJECT or settings.GCP_PROJECT_ID
        if not project:
            log.debug(
                "firestore_trace_skipped",
                reason="GOOGLE_CLOUD_PROJECT not set",
                trace_id=trace.trace_id,
            )
            return False

        from google.cloud import firestore  # google-cloud-firestore

        db = firestore.AsyncClient(project=project)

        doc_data = {
            "trace_id":          trace.trace_id,
            "user_id":           trace.user_id,
            "session_id":        trace.session_id,
            "user_message":      trace.user_message,
            "agents_involved":   trace.agents_involved,
            "total_duration_ms": trace.total_duration_ms,
            "step_count":        len(trace.steps),
            "success":           trace.success,
            "error":             trace.error,
            "final_response_len": len(trace.final_response),
            "started_at":        trace.started_at,
            # Store step summaries (not full detail) to keep docs lean
            "step_summaries": [
                {
                    "kind":        s.kind.value,
                    "agent_label": s.agent_label,
                    "tool_name":   s.tool_name,
                    "summary":     s.summary,
                    "duration_ms": s.duration_ms,
                    "status":      s.status,
                }
                for s in trace.steps
            ],
        }

        await db.collection(_COLLECTION).document(trace.trace_id).set(doc_data)

        log.info(
            "firestore_trace_persisted",
            trace_id=trace.trace_id,
            agents=trace.agents_involved,
            steps=len(trace.steps),
            project=project,
        )
        return True

    except ImportError:
        log.debug(
            "firestore_trace_skipped",
            reason="google-cloud-firestore not installed — run: pip install google-cloud-firestore",
        )
        return False

    except Exception as exc:
        # Never crash the main application — trace persistence is best-effort
        log.warning(
            "firestore_trace_failed",
            error=str(exc),
            trace_id=getattr(trace, "trace_id", "unknown"),
        )
        return False


async def query_traces(
    user_id: str,
    limit: int = 20,
    success_only: bool = False,
) -> list[dict]:
    """
    Query recent agent traces for a user from Firestore.
    Returns an empty list if Firestore is not configured.
    """
    try:
        from src.core.config import settings

        project = settings.GOOGLE_CLOUD_PROJECT or settings.GCP_PROJECT_ID
        if not project:
            return []

        from google.cloud import firestore

        db = firestore.AsyncClient(project=project)
        query = (
            db.collection(_COLLECTION)
            .where("user_id", "==", user_id)
            .order_by("started_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )

        if success_only:
            query = query.where("success", "==", True)

        docs = query.stream()
        results = []
        async for doc in docs:
            results.append(doc.to_dict())

        log.info("firestore_traces_queried", user_id=user_id, count=len(results))
        return results

    except Exception as exc:
        log.warning("firestore_query_failed", error=str(exc))
        return []
