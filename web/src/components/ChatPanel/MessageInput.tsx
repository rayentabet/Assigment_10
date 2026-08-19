import { useRef, useState } from "react";
import type { FormEvent } from "react";

import { transcribeAudio } from "../../api/client";
import "./ChatPanel.css";

interface MessageInputProps {
  disabled: boolean;
  placeholder: string;
  threadId: string | null;
  onSend: (message: string) => void;
}

// Extension is cosmetic only: the backend decodes the container from its
// bytes (via PyAV), not from this filename.
const EXTENSION_BY_MIME_TYPE: Record<string, string> = {
  "audio/webm": "webm",
  "audio/ogg": "ogg",
  "audio/mp4": "m4a",
};

export function MessageInput({ disabled, placeholder, threadId, onSend }: MessageInputProps) {
  const [value, setValue] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function stopStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function startRecording() {
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => void handleRecordingStopped(recorder.mimeType);
      recorder.start();
      recorderRef.current = recorder;
      setIsRecording(true);
    } catch {
      setMicError("Microphone access was denied or is unavailable.");
      stopStream();
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
    setIsRecording(false);
  }

  async function handleRecordingStopped(mimeType: string) {
    stopStream();
    const audioBlob = new Blob(chunksRef.current, { type: mimeType });
    chunksRef.current = [];
    if (!threadId || audioBlob.size === 0) return;

    const extension = EXTENSION_BY_MIME_TYPE[mimeType.split(";")[0]] ?? "webm";
    setIsTranscribing(true);
    try {
      const { text } = await transcribeAudio(threadId, audioBlob, `voice-message.${extension}`);
      setValue((previous) => (previous.trim() ? `${previous.trim()} ${text}` : text));
    } catch (err) {
      setMicError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTranscribing(false);
    }
  }

  const micDisabled = disabled || !threadId || isTranscribing;

  return (
    <form className="message-input-wrapper" onSubmit={handleSubmit}>
      <div className="message-input">
        <button
          type="button"
          className={`mic-button${isRecording ? " recording" : ""}`}
          disabled={micDisabled}
          onClick={isRecording ? stopRecording : () => void startRecording()}
          title={isRecording ? "Stop recording" : "Record a voice message (transcribed locally)"}
          aria-pressed={isRecording}
          aria-label={isRecording ? "Stop recording" : "Record a voice message"}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path
              fill="currentColor"
              d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12z"
            />
          </svg>
        </button>
        <input
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={
            isRecording ? "Recording…" : isTranscribing ? "Transcribing…" : placeholder
          }
          disabled={disabled}
        />
        <button
          type="submit"
          className="sidebar-button primary"
          disabled={disabled || !value.trim()}
        >
          Send
        </button>
      </div>
      {micError && <p className="error-text mic-error">{micError}</p>}
    </form>
  );
}
