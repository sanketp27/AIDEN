from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def main() -> None:
    print("AIDEN — Gemini Embeddings Verification")
    print("=" * 45)

    from src.repositories.vector_repo import (
        VectorRepository,
        _embed_documents,
        _embed_query,
    )

    print("\n[1/4] Generating document embedding via Gemini text-embedding-004…")
    try:
        doc_vecs = await _embed_documents(["AIDEN multi-agent productivity system"])
        assert len(doc_vecs) == 1,     f"Expected 1 vector, got {len(doc_vecs)}"
        assert len(doc_vecs[0]) == 768, f"Expected 768 dims, got {len(doc_vecs[0])}"
        print(f"      ✓  768-dimensional vector returned  (model: text-embedding-004)")
    except Exception as e:
        print(f"      ✗  FAILED: {e}")
        sys.exit(1)

    print("\n[2/4] Generating query embedding (RETRIEVAL_QUERY task_type)…")
    try:
        q_vec = await _embed_query("quarterly board meeting preparation")
        assert len(q_vec) == 768, f"Expected 768 dims, got {len(q_vec)}"
        print(f"      ✓  768-dimensional query vector returned")
    except Exception as e:
        print(f"      ✗  FAILED: {e}")
        sys.exit(1)

    print("\n[3/4] Storing test documents in ChromaDB and running semantic search…")
    TEST_USER = "_verify_test_user_"
    repo      = VectorRepository()

    try:
        await repo.add_embedding(
            TEST_USER, "verify_doc_1",
            "Board meeting agenda: Q2 revenue, headcount, and roadmap review",
            {"title": "Board Meeting"},
        )
        await repo.add_embedding(
            TEST_USER, "verify_doc_2",
            "Python async programming patterns with asyncio and FastAPI",
            {"title": "Engineering Notes"},
        )
        await repo.add_embedding(
            TEST_USER, "verify_doc_3",
            "Contract negotiation strategy for senior engineering hire",
            {"title": "Hiring Notes"},
        )
        print("      ✓  3 documents stored with Gemini embeddings")

        results = await repo.semantic_search(TEST_USER, "quarterly board presentation", top_k=3)
        assert len(results) > 0, "No results returned"
        top     = results[0]
        assert "score" in top,       "Missing 'score' field"
        assert 0 <= top["score"] <= 1, f"Score out of range: {top['score']}"

        print(f"      ✓  Semantic search returned {len(results)} result(s)")
        print(f"         Top match: \"{top['metadata'].get('title', '?')}\"  "
              f"(score: {top['score']:.3f})")

        # Confirm board meeting is the top result (semantically closest)
        assert "Board" in top["metadata"].get("title", ""), (
            f"Expected 'Board Meeting' as top result, got: {top['metadata'].get('title')}"
        )
        print("      ✓  Top result is semantically correct ('Board Meeting')")

    except Exception as e:
        print(f"      ✗  FAILED: {e}")
        sys.exit(1)
    finally:
        try:
            await repo.delete_user_collection(TEST_USER)
        except Exception:
            pass

    print("\n[4/4] API endpoint check (requires running server)…")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("http://localhost:8000/health")
            if r.status_code == 200:
                print("      ✓  Server is running at localhost:8000")
                print("         Hit GET /notes/search/verify (with auth token) to confirm end-to-end")
            else:
                print("      ⚠  Server returned non-200 — is it running?")
    except Exception:
        print("      ⚠  Server not reachable at localhost:8000 — skipping API check")
        print("         Start the server and hit: GET /notes/search/verify")

    print("\n" + "=" * 45)
    print("✅  All embedding checks passed!")
    print("    Model : text-embedding-004")
    print("    Dims  : 768")
    print("    Store : ChromaDB (cosine similarity)")
    print("    Scope : per-user isolated collections")


if __name__ == "__main__":
    asyncio.run(main())
