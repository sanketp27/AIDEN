from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends

from src.api.middleware import get_current_active_user
from src.models.note import Note, NoteCreate
from src.models.task import Priority, Task, TaskStatus
from src.models.user import UserClaims
from src.repositories.notes_repo import NotesRepository
from src.repositories.task_repo import TaskRepository
from src.repositories.vector_repo import VectorRepository

log    = structlog.get_logger()
router = APIRouter(prefix="/demo", tags=["Demo"])

_TASKS = [
    {
        "title":       "Review Q2 product roadmap",
        "description": "Align on priorities with design and engineering leads before board meeting.",
        "priority":    Priority.P1,
        "status":      TaskStatus.TODO,
        "due_days":    1,
        "tags":        ["Q2", "roadmap", "strategy"],
    },
    {
        "title":       "Prepare board presentation deck",
        "description": "Slides covering Q2 results, H2 plan, and headcount ask.",
        "priority":    Priority.P1,
        "status":      TaskStatus.IN_PROGRESS,
        "due_days":    2,
        "tags":        ["board", "presentation"],
    },
    {
        "title":       "Follow up with Alex on contract",
        "description": "Send counter-offer and loop in legal before end of week.",
        "priority":    Priority.P2,
        "status":      TaskStatus.TODO,
        "due_days":    3,
        "tags":        ["hiring", "contracts"],
    },
    {
        "title":       "Sync with design team on v2 UI",
        "description": "Review Figma prototypes for the new dashboard and agent trace panel.",
        "priority":    Priority.P2,
        "status":      TaskStatus.TODO,
        "due_days":    4,
        "tags":        ["design", "v2"],
    },
    {
        "title":       "Write weekly status email",
        "description": "Summarise week's progress for stakeholders. Include OKR update.",
        "priority":    Priority.P3,
        "status":      TaskStatus.TODO,
        "due_days":    5,
        "tags":        ["communication"],
    },
    {
        "title":       "Research competitor pricing",
        "description": "Benchmark our pricing against Competitor X and Y. Report due Monday.",
        "priority":    Priority.P3,
        "status":      TaskStatus.COMPLETED,
        "due_days":    -2,
        "tags":        ["research", "competitive"],
    },
]

_NOTES = [
    {
        "title":   "Board Meeting — Key Talking Points",
        "content": (
            "Q2 revenue up 18% YoY. Three risk areas to address:\n\n"
            "1. Engineering headcount gap — need 4 hires by June to hit roadmap.\n"
            "2. Cloud infra costs trending 12% over budget — Sam owns reduction plan.\n"
            "3. Competitor X launched a similar feature last week — need differentiation story.\n\n"
            "Action items agreed in pre-meeting:\n"
            "- Alex owns the hiring plan (due Friday)\n"
            "- Sam owns the cost reduction proposal (due EOW)\n"
            "- I own the differentiation narrative for the deck (due Wednesday)\n\n"
            "Key metric to lead with: NPS jumped from 34 → 51 this quarter."
        ),
        "tags":    ["board", "Q2", "strategy"],
        "project": "Board Prep",
    },
    {
        "title":   "AIDEN v2 Architecture Notes",
        "content": (
            "Decided to move from monolith to multi-agent architecture for v2.\n\n"
            "Agent roster:\n"
            "- Orchestrator (aiden_core): routes all user intents\n"
            "- TaskMaster: CRUD for tasks, priority management\n"
            "- CalendarBot: Google Calendar API v3 (OAuth2)\n"
            "- NoteKeeper: notes + ChromaDB semantic search\n"
            "- VoiceAgent: Gemini Live real-time audio\n"
            "- VisionAgent: Gemini vision for image analysis\n\n"
            "Stack: FastAPI + Google ADK + MongoDB + ChromaDB (Gemini embeddings).\n"
            "Deploy: Cloud Run + Vertex AI. Target 99.9% uptime SLA.\n\n"
            "Key design decision: each agent is stateless; all state lives in MongoDB.\n"
            "This makes horizontal scaling trivial on Cloud Run."
        ),
        "tags":    ["architecture", "v2", "engineering"],
        "project": "AIDEN",
    },
    {
        "title":   "Alex — Contract Negotiation Notes",
        "content": (
            "Position: Senior Staff Engineer (IC6 equivalent).\n\n"
            "Alex's ask:\n"
            "- $195k base salary\n"
            "- 15% equity (4-year vest, 1-year cliff)\n"
            "- Remote-first, one on-site week per quarter\n\n"
            "Our current band: $170–185k base, 10–13% equity.\n\n"
            "Comparable offers (from Glassdoor + LinkedIn data):\n"
            "- Competitor Y: ~$180k + 11%\n"
            "- Competitor Z: ~$175k + 12%\n\n"
            "Next steps:\n"
            "1. Loop in Legal (Sarah) for equity structure review\n"
            "2. Counter at $183k + 12.5% — meet in the middle\n"
            "3. Decision deadline: this Friday EOD\n\n"
            "Personal note: Alex cares most about scope and autonomy — emphasise "
            "the green-field opportunity on the AI platform."
        ),
        "tags":    ["hiring", "contracts", "alex", "negotiation"],
        "project": "Hiring",
    },
]


async def _upsert_task(
    repo: TaskRepository,
    user_id: str,
    data: dict,
) -> str:
    """Insert task if no task with same title exists for this user."""
    now = datetime.now(timezone.utc)
    existing = await repo.list_tasks(user_id)
    for t in existing:
        if t.title == data["title"]:
            return str(t.task_id)

    task = Task(
        user_id     = user_id,
        title       = data["title"],
        description = data.get("description"),
        priority    = data["priority"],
        status      = data["status"],
        due_date    = now + timedelta(days=data["due_days"]),
        tags        = data.get("tags", []),
    )
    doc = await repo.create_task(task)
    return doc["task_id"]


async def _upsert_note(
    notes_repo:  NotesRepository,
    vector_repo: VectorRepository,
    user_id:     str,
    data:        dict,
) -> str:
    """Insert note if no note with same title exists; index embedding."""
    existing = await notes_repo.list_notes(user_id)
    for n in existing:
        if n.title == data["title"]:
            return str(n.note_id)

    note = Note(
        user_id = user_id,
        title   = data["title"],
        content = data["content"],
        tags    = data.get("tags", []),
        project = data.get("project"),
    )
    doc = await notes_repo.create_note(note)

    # Index in ChromaDB for semantic search
    await vector_repo.add_embedding(
        user_id     = user_id,
        document_id = note.note_id,
        text        = f"{note.title}\n{note.content}",
        metadata    = {"type": "note", "title": note.title, "tags": note.tags},
    )

    return doc["note_id"]


@router.post("/seed")
async def seed_demo_data(
    user: UserClaims = Depends(get_current_active_user),
) -> dict:
    """
    Populate the authenticated user's account with realistic demo data.

    Idempotent — safe to call multiple times (upserts by title).
    Returns counts of seeded tasks and notes.
    """
    uid        = user.user_id
    task_repo  = TaskRepository()
    notes_repo = NotesRepository()
    vector_repo = VectorRepository()

    log.info("demo_seed_start", user_id=uid)

    # Parallelise all inserts
    task_coros = [_upsert_task(task_repo, uid, t) for t in _TASKS]
    note_coros = [_upsert_note(notes_repo, vector_repo, uid, n) for n in _NOTES]

    task_ids, note_ids = await asyncio.gather(
        asyncio.gather(*task_coros),
        asyncio.gather(*note_coros),
    )

    log.info("demo_seed_complete", user_id=uid, tasks=len(task_ids), notes=len(note_ids))

    return {
        "success": True,
        "seeded": {
            "tasks": len(task_ids),
            "notes": len(note_ids),
        },
        "suggested_prompts": [
            "Plan my week",
            "Prepare for the board meeting",
            "What did I write about the contract negotiation?",
            "What tasks do I have this week?",
        ],
        "message": (
            f"Demo data ready: {len(task_ids)} tasks and {len(note_ids)} notes loaded. "
            "Try the workflow buttons above to see multi-agent coordination in action."
        ),
    }
