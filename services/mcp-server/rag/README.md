# Embedded RAG runtime

This directory contains the runtime portion of the former Assignment 8 RAG so
the repository can run and be submitted independently.

Included:

- retrieval, reranking, Gemini embedding, and grounded-answer code;
- only image assets referenced by the shipped Qdrant collection snapshot.

Excluded because the running application does not need them:

- Assignment 8's virtual environment, Git history, reports, raw PDFs, caches,
  ingestion pipeline, duplicate dashboards, and upload directories.

The relative `:data/...` and `chunks/...` paths are retained because they are
stored in Qdrant payloads. Do not rename those asset directories without also
rebuilding the Qdrant collection.
