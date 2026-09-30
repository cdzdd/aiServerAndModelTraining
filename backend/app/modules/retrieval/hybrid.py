"""Reciprocal rank fusion changes ordering; hit scores remain cosine similarity."""


def fuse(vector_hits, lexical_hits, top_k, rank_constant=60):
    scores, hits = {}, {}
    for ranking in (vector_hits, lexical_hits):
        for rank, hit in enumerate(ranking, 1):
            hits[hit.chunk_id] = hit
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0) + 1 / (rank_constant + rank)
    lexical_ids = {hit.chunk_id for hit in lexical_hits}
    ordered = sorted(
        hits, key=lambda chunk_id: (-scores[chunk_id], chunk_id not in lexical_ids, chunk_id)
    )
    return [hits[chunk_id] for chunk_id in ordered[:top_k]]
