// Fetch wrapper for the FastAPI application: raise a
// readable Error on HTTP failure or when the API is unreachable, otherwise
// parse and return the JSON body.

import type {
  ChatResponse,
  DigiKeyConnectionStatus,
  PaymentCredential,
  SandboxCard,
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

export async function transcribeAudio(
  threadId: string,
  audio: Blob,
  filename: string,
): Promise<TranscriptionResponse> {
  // Multipart upload, so this bypasses request()'s JSON-only body handling.
  const form = new FormData();
  form.append("audio", audio, filename);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/threads/${threadId}/transcribe`, {
      method: "POST",
      body: form,
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
  return (await response.json()) as TranscriptionResponse;
}

export function resumeThread(
  threadId: string,
  approved: boolean,
  paymentCredentialId?: string,
): Promise<ChatResponse> {
  return request<ChatResponse>("POST", `/threads/${threadId}/resume`, {
    approved,
    payment_credential_id: paymentCredentialId ?? null,
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
