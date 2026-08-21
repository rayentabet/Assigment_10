import json
import os

from google import genai

from rag.gemini_generation import generate

MODEL = "gemini-3.1-flash-lite"
MULTIQUERY_SYSTEM_PROMPT = """
You generate retrieval queries for an Arduino sensor documentation RAG system.

Return 1–3 concise search queries as valid JSON:
{"queries": ["query 1", "query 2"]}

Rules:
- Preserve the user's meaning.
- Preserve technical names, model numbers, board names, pins, voltages,
  interfaces, and protocols exactly.
- Correct only obvious natural-language spelling errors.
- Never answer the question or invent missing technical information.
- Split a query when it contains multiple information needs, such as
  wiring instructions and expected experiment behaviour.
- Use relevant documentation terminology when supported by the question:
  Specification, Hardware Connection, Pins Definition, Sample Code,
  Experiment Result, wiring diagram, or pinout diagram.
- For questions explicitly about Arduino UNO pins, use "Arduino UNO R3".
- Do not add a section name that is unrelated to the user's request.
- Remove duplicate queries.
- Return JSON only, without Markdown or explanatory text.
"""


def analyze_query(query):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    try:
        response = generate(
            client,
            MODEL,
            f"{MULTIQUERY_SYSTEM_PROMPT}\n\nUser query:\n{query}",
        )
        content = response.text
        content = content.replace("```json", "").replace("```", "").strip()
        improved_queries = json.loads(content)["queries"][:3]
    except Exception:
        return [query]

    queries = [query]
    for improved_query in improved_queries:
        if improved_query and improved_query not in queries:
            queries.append(improved_query)
    return queries
