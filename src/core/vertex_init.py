from __future__ import annotations

import os
import structlog

log = structlog.get_logger()


def init_vertex(project_id: str, location: str = "us-central1") -> None:
    """
    Initialise the Vertex AI SDK and configure the ADK/genai routing flag.

    Parameters
    ----------
    project_id : str
        GCP project ID (e.g. "my-aiden-project").
    location : str
        GCP region for Vertex AI (default: us-central1).
    """
    try:
        import vertexai  # google-cloud-aiplatform
        vertexai.init(project=project_id, location=location)
        log.info("vertexai_sdk_initialised", project=project_id, location=location)
    except ImportError:
        log.warning(
            "vertexai_import_failed",
            hint="Run: pip install google-cloud-aiplatform>=1.60.0",
        )

    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
    os.environ["GOOGLE_CLOUD_PROJECT"]      = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"]     = location

    log.info(
        "vertex_ai_routing_enabled",
        project=project_id,
        location=location,
        env_var="GOOGLE_GENAI_USE_VERTEXAI=1",
    )
