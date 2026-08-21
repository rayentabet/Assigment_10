import mimetypes
import os
from pathlib import Path

from google import genai
from google.genai import types

from rag.contracts import RAGResponse, RetrievedContext
from rag.gemini_generation import generate
from rag.retrieval import search

MODEL = "gemini-3.1-flash-lite"
RAG_ROOT = Path(__file__).resolve().parent


class GeminiRAGAdapter:
    def answer(self, question: str, record_id: str) -> RAGResponse:
        results = search(question, limit=5, modality="text")

        contexts = [
            RetrievedContext(
                text=result["text"],
                source_id=result["source_document"],
                location=result["source_location"],
                image_path=result.get("image_path", ""),
            )
            for result in results
        ]

        context_text = "\n\n".join(
            f"Context {number}:\n{context.text}"
            for number, context in enumerate(contexts, 1)
        )

        prompt = f"""Answer the question using only the provided contexts.
Some retrieved contexts may be irrelevant to the question.
Image captions are valid evidence for information visible in diagrams,
including dimensions, labels, pins, and connections.
If the answer is not in the contexts, say that you do not know.
When authoritative document text conflicts with an image caption, follow the
authoritative document text.
Keep the answer concise.

Question:
{question}

Contexts:
{context_text}
"""

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        contents = [prompt]
        for context in contexts:
            if context.image_path:
                path = (RAG_ROOT / context.image_path).resolve()
                if not path.is_relative_to(RAG_ROOT) or not path.is_file():
                    continue
                contents.append(
                    types.Part.from_bytes(
                        data=path.read_bytes(),
                        mime_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                    )
                )

        response = generate(client, MODEL, contents)

        return RAGResponse(answer=response.text, contexts=contexts)


adapter = GeminiRAGAdapter()
