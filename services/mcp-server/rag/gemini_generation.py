import os
import threading
import time

lock = threading.Lock()
last_request_time = 0


def requests_per_minute():
    value = int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "10"))
    if value < 1:
        raise ValueError("GEMINI_REQUESTS_PER_MINUTE must be at least 1")
    return value


def generate(client, model, contents):
    global last_request_time

    with lock:
        minimum_interval = 60 / requests_per_minute()
        elapsed = time.monotonic() - last_request_time
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        last_request_time = time.monotonic()

        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
            )
        except Exception as error:
            if "429" not in str(error):
                raise

            time.sleep(30)
            last_request_time = time.monotonic()
            response = client.models.generate_content(
                model=model,
                contents=contents,
            )
        return response
