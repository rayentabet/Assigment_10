import os

os.environ["USE_TF"] = "0"
os.environ["USE_FLAX"] = "0"


MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANK_WEIGHT = 0.7
reranker = None


def normalize(values):
    lowest, highest = min(values), max(values)
    if highest - lowest < 1e-9:
        return [0.5 for _ in values]
    return [(value - lowest) / (highest - lowest) for value in values]


def candidate_text(candidate):
    location = candidate.get("source_location", "")
    location_parts = [
        part.strip() for part in location.split(">") if part.strip()
    ]
    project = next(
        (
            part
            for part in location_parts
            if part.lower().startswith("project")
        ),
        "",
    )
    section = location_parts[-1] if location_parts else location

    return (
        f"Document: {candidate.get('source_document', '')}\n"
        f"Project: {project}\n"
        f"Section: {section}\n"
        f"Location: {location}\n"
        f"Content:\n{candidate['text']}"
    )


def rerank(query, candidates, limit):
    global reranker
    from sentence_transformers import CrossEncoder

    if reranker is None:
        reranker = CrossEncoder(MODEL)

    pairs = [
        (query, candidate_text(candidate))
        for candidate in candidates
    ]
    scores = reranker.predict(pairs)

    normalized_rerank = normalize([float(score) for score in scores])
    normalized_rrf = normalize(
        [candidate.get("rrf_score", 0) for candidate in candidates]
    )

    for candidate, score, rerank_norm, rrf_norm in zip(
        candidates, scores, normalized_rerank, normalized_rrf, strict=True
    ):
        candidate["rerank_score"] = float(score)
        candidate["combined_score"] = (
            RERANK_WEIGHT * rerank_norm + (1 - RERANK_WEIGHT) * rrf_norm
        )

    return sorted(
        candidates,
        key=lambda candidate: candidate["combined_score"],
        reverse=True,
    )[:limit]
