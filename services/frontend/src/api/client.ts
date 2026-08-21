// Fetch wrapper for the FastAPI application: raise a
// readable Error on HTTP failure or when the API is unreachable, otherwise
// parse and return the JSON body.

import type {
  ChatResponse,
  DigiKeyConnectionStatus,
  PaymentCredential,
  SandboxCard,
  StreamFrame,
  ThreadHistoryResponse,
  ThreadListResponse,
  ThreadResponse,
  TranscriptionResponse,
} from "./types";

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "https://localhost:8000"
).replace(/\/$/, "");

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(`Cannot connect to the API at ${API_BASE_URL}. Start FastAPI first.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Non-JSON error body; fall back to statusText.
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  if (response.status === 204) {
    return {} as T;
  }
  return (await response.json()) as T;
}

export function createThread(): Promise<ThreadResponse> {
  return request<ThreadResponse>("POST", "/threads");
}

export function listThreads(): Promise<ThreadListResponse> {
  return request<ThreadListResponse>("GET", "/threads");
}

export function getThreadHistory(threadId: string): Promise<ThreadHistoryResponse> {
  return request<ThreadHistoryResponse>("GET", `/threads/${threadId}/messages`);
}

export function deleteThread(threadId: string): Promise<void> {
  return request<void>("DELETE", `/threads/${threadId}`);
}

export function sendMessage(threadId: string, message: string): Promise<ChatResponse> {
  return request<ChatResponse>("POST", `/threads/${threadId}/messages`, { message });
}

async function requestStream(method: string, path: string, body?: unknown): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(`Cannot connect to the API at ${API_BASE_URL}. Start FastAPI first.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Non-JSON error body; fall back to statusText.
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response;
}

// Parses an SSE body (`data: {json}\n\n` frames) into a stream of typed
// values. Manual parsing, not EventSource, because these endpoints are POST
// with a JSON body and EventSource only supports GET.
async function* streamFrames<T>(response: Response): AsyncGenerator<T> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let separatorIndex: number;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawFrame = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const dataLine = rawFrame.split("\n").find((line) => line.startsWith("data: "));
      if (dataLine) yield JSON.parse(dataLine.slice("data: ".length)) as T;
    }
  }
}

export async function* streamMessage(
  threadId: string,
  message: string,
): AsyncGenerator<StreamFrame> {
  const response = await requestStream("POST", `/threads/${threadId}/messages/stream`, {
    message,
  });
  yield* streamFrames<StreamFrame>(response);
}

export async function* streamResume(
  threadId: string,
  approved: boolean,
  paymentMethodId?: string,
): AsyncGenerator<StreamFrame> {
  const response = await requestStream("POST", `/threads/${threadId}/resume/stream`, {
    approved,
    payment_method_id: paymentMethodId ?? null,
  });
  yield* streamFrames<StreamFrame>(response);
}

export async function transcribeAudio(
  threadId: string,
  audio: Blob,
  filename: string,
): Promise<TranscriptionResponse> {
  // Multipart upload, so this bypasses request()'s JSON-only body handling.
  const form = new FormData();
  form.append("audio", audio, filename);

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 90_000);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/threads/${threadId}/transcribe`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(
        "Transcription timed out. The local speech model may still be downloading; try again shortly.",
      );
    }
    throw new Error(`Cannot connect to the API at ${API_BASE_URL}. Start FastAPI first.`);
  } finally {
    window.clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Non-JSON error body; fall back to statusText.
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return (await response.json()) as TranscriptionResponse;
}

export function resumeThread(
  threadId: string,
  approved: boolean,
  paymentMethodId?: string,
): Promise<ChatResponse> {
  return request<ChatResponse>("POST", `/threads/${threadId}/resume`, {
    approved,
    payment_method_id: paymentMethodId ?? null,
  });
}

export function tokenizeSandboxCard(card: SandboxCard): Promise<PaymentCredential> {
  return request<PaymentCredential>("POST", "/payments/sandbox/tokenize", card);
}

export function forgetSandboxCard(credentialId: string): Promise<void> {
  return request<void>(
    "DELETE",
    `/payments/sandbox/credentials/${encodeURIComponent(credentialId)}`,
  );
}

export function getPaymentConfig(): Promise<import("./types").PaymentConfig> {
  return request("GET", "/payments/config");
}

export function createLithicMethod(): Promise<PaymentCredential> {
  return request("POST", "/payments/lithic/methods");
}

export function artifactUrl(imageUrl: string): string {
  return `${API_BASE_URL}${imageUrl}`;
}

export function digikeyAuthorizationUrl(): string {
  return `${API_BASE_URL}/auth/digikey/start`;
}

export function getDigiKeyStatus(): Promise<DigiKeyConnectionStatus> {
  return request<DigiKeyConnectionStatus>("GET", "/auth/digikey/status");
}

export function disconnectDigiKey(): Promise<void> {
  return request<void>("DELETE", "/auth/digikey/connection");
}
