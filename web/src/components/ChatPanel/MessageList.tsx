import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { DisplayMessage } from "../../hooks/useConversation";
import "./ChatPanel.css";

interface MessageListProps {
  messages: DisplayMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <p className="muted empty-state">
        Ask about robotics, Arduino code, wiring, or a component purchase.
      </p>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message, index) => (
        <div key={index} className={`message message-${message.role}`}>
          <span className="message-role">{message.role === "user" ? "You" : "Assistant"}</span>
          <div className="message-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  );
}
