import os
import re

from google import genai
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from rag.embedding.embeddings import embed_text

from .query_analyzer import analyze_query
from .reranker import rerank


def tokenize(text):
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())


def project_location(location):
    parts = [part.strip() for part in location.split(">")]
    project_parts = [
        part for part in parts if part.lower().startswith("project ")
    ]
    return project_parts[0] if project_parts else ""


def add_hardware_text_to_captions(candidates, stored_points):
    hardware_by_project = {}

    for point in stored_points:
        payload = point.payload
        location = payload.get("source_location", "")
        if location.lower().endswith("hardware connection"):
            project = project_location(location)
            if project:
                hardware_by_project[
                    (payload.get("source_document", ""), project)
                ] = payload["text"]

    for candidate in candidates:
        if candidate.get("content_type") != "image_caption":
            continue

        project = project_location(candidate.get("source_location", ""))
        hardware_text = hardware_by_project.get(
            (candidate.get("source_document", ""), project)
        )
        if hardware_text:
            candidate["text"] = (
                "Authoritative document text:\n"
                f"{hardware_text}\n\n"
                "Image caption (use only for additional visual details):\n"
                f"{candidate['text']}"
            )


def search_with_trace(query: str, limit: int = 5, modality="text"):
    """Return the final results plus the rankings around the reranker.

    The trace is intentionally evaluation-oriented: production callers can
    continue using ``search`` while ranking evaluation can compare the RRF
    candidate order with the cross-encoder order on the exact same pool.
    """
    gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    qdrant = QdrantClient(
        url=os.environ["QDRANT_URL"],
        check_compatibility=False,
    )
    collection = os.environ["QDRANT_COLLECTION"]
    retrieval_limit = max(limit * 4, 20)
    rerank_candidate_limit = max(limit * 6, 30)
    queries = analyze_query(query)

    stored_points, _ = qdrant.scroll(
        collection_name=collection,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="modality",
                    match=models.MatchValue(value=modality),
                )
            ]
        ),
        limit=10000,
        with_payload=True,
        with_vectors=False,
    )
    bm25 = BM25Okapi(
        [tokenize(point.payload["text"]) for point in stored_points]
    )
    fused = {}

    for search_query in queries:
        vector_results = qdrant.query_points(
            collection_name=collection,
            query=embed_text(gemini, search_query),
            limit=retrieval_limit,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="modality",
                        match=models.MatchValue(value=modality),
                    )
                ]
            ),
        ).points

        bm25_scores = bm25.get_scores(tokenize(search_query))
        bm25_order = sorted(
            [
                index
                for index in range(len(stored_points))
                if bm25_scores[index] > 0
            ],
            key=lambda index: bm25_scores[index],
            reverse=True,
        )[:retrieval_limit]

        for rank, result in enumerate(vector_results, 1):
            point_id = str(result.id)
            if point_id not in fused:
                fused[point_id] = {
                    **result.payload,
                    "rrf_score": 0,
                }
            fused[point_id]["vector_score"] = result.score
            fused[point_id]["vector_rank"] = rank
            fused[point_id]["rrf_score"] += 1 / (60 + rank)

        for rank, index in enumerate(bm25_order, 1):
            point = stored_points[index]
            point_id = str(point.id)
            if point_id not in fused:
                fused[point_id] = {
                    **point.payload,
                    "rrf_score": 0,
                }
            fused[point_id]["bm25_score"] = float(bm25_scores[index])
            fused[point_id]["bm25_rank"] = rank
            fused[point_id]["rrf_score"] += 1 / (60 + rank)

    candidates = sorted(
        fused.values(),
        key=lambda result: result["rrf_score"],
        reverse=True,
    )[:rerank_candidate_limit]
    add_hardware_text_to_captions(candidates, stored_points)
    pre_rerank = [dict(candidate) for candidate in candidates]
    reranked = rerank(query, candidates, len(candidates))
    results = reranked[:limit]

    for result in reranked:
        result["score"] = result["combined_score"]
        result["search_queries"] = queries
        result["candidate_pool_size"] = len(candidates)

    return {
        "query": query,
        "limit": limit,
        "pre_rerank": pre_rerank,
        "post_rerank": reranked,
        "results": results,
    }


def search(query: str, limit: int = 5, modality="text"):
    return search_with_trace(query, limit=limit, modality=modality)["results"]
