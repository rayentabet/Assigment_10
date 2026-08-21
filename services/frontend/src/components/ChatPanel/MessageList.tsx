import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { artifactUrl } from "../../api/client";
import type { DisplayMessage } from "../../hooks/useConversation";
import "./ChatPanel.css";

interface MessageListProps {
  messages: DisplayMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
            <path
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.7 9.7 0 0 1-3.5-.64L3 20l1.1-3.3A7.9 7.9 0 0 1 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8Z"
            />
          </svg>
        </div>
        <p>Ask about robotics, Arduino code, wiring, or a component purchase.</p>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message, index) => (
        <div key={index} className={`message-row message-row-${message.role}`}>
          <div className="message-avatar" aria-hidden="true">
            {message.role === "user" ? "U" : "AI"}
          </div>
          <div className={`message message-${message.role}`}>
            <span className="message-role">{message.role === "user" ? "You" : "Assistant"}</span>
            <div className="message-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
            {message.imageUrls && message.imageUrls.length > 0 && (
              <div className="image-gallery">
                {message.imageUrls.map((url) => (
                  <img key={url} src={artifactUrl(url)} alt="Agent-generated artifact" />
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
