import mimetypes
import os
import time
from pathlib import Path

import httpx
from google.genai import types
from google.genai.errors import ClientError

MODEL = "gemini-embedding-2"
VECTOR_SIZE = 768
last_request_time = 0


def wait_for_rate_limit():
    global last_request_time

    requests_per_minute = int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "10"))
    if requests_per_minute < 1:
        raise ValueError("GEMINI_REQUESTS_PER_MINUTE must be at least 1")

    minimum_interval = 60 / requests_per_minute
    elapsed = time.monotonic() - last_request_time
    if elapsed < minimum_interval:
        time.sleep(minimum_interval - elapsed)
    last_request_time = time.monotonic()


def embed_text(client, text):
    wait_for_rate_limit()
    result = client.models.embed_content(
        model=MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=VECTOR_SIZE),
    )
    return result.embeddings[0].values


def embed_batch(client, chunks):
    wait_for_rate_limit()
    contents = []

    for chunk in chunks:
        if chunk["modality"] == "text":
            part = types.Part.from_text(text=chunk["text"])
        else:
            path = Path(chunk["image_path"])
            mime_type = mimetypes.guess_type(path)[0]
            part = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)
        contents.append(types.Content(parts=[part]))

    result = client.models.embed_content(
        model=MODEL,
        contents=contents,
        config=types.EmbedContentConfig(output_dimensionality=VECTOR_SIZE),
    )
    return [embedding.values for embedding in result.embeddings]


def embed_batch_with_retry(client, chunks):
    while True:
        try:
            return embed_batch(client, chunks)
        except ClientError as error:
            if error.code != 429:
                raise
            print("Gemini rate limit reached. Waiting 30 seconds...")
            time.sleep(30)
        except httpx.HTTPError:
            print("Temporary network error. Waiting 10 seconds...")
            time.sleep(10)
