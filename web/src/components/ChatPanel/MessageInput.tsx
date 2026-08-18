import { useState } from "react";
import type { FormEvent } from "react";

import "./ChatPanel.css";

interface MessageInputProps {
  disabled: boolean;
  placeholder: string;
  onSend: (message: string) => void;
}

export function MessageInput({ disabled, placeholder, onSend }: MessageInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form className="message-input" onSubmit={handleSubmit}>
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
      <button type="submit" className="sidebar-button primary" disabled={disabled || !value.trim()}>
        Send
      </button>
    </form>
  );
}
