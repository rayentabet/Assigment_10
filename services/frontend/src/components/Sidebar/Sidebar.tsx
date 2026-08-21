import { useState } from "react";

import { API_BASE_URL } from "../../api/client";
import { useThreadsQuery } from "../../api/hooks";
import "./Sidebar.css";

interface SidebarProps {
  currentThreadId: string | null;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
  onDeleteThread: (threadId: string) => void;
  isDeleting: boolean;
}

export function Sidebar({
  currentThreadId,
  onSelectThread,
  onNewChat,
  onDeleteThread,
  isDeleting,
}: SidebarProps) {
  const threads = useThreadsQuery();
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <h2>Conversation</h2>
        <button type="button" onClick={onNewChat} className="sidebar-button primary">
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
            <path fill="currentColor" d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z" />
          </svg>
          New chat
        </button>
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          disabled={!currentThreadId || isDeleting}
          className="sidebar-button"
        >
          Delete current chat
        </button>
        {confirmDelete && (
          <div className="confirm-delete">
            <p>Delete this conversation permanently?</p>
            <div className="confirm-delete-actions">
              <button
                type="button"
                className="sidebar-button danger"
                disabled={isDeleting}
                onClick={() => {
                  if (currentThreadId) onDeleteThread(currentThreadId);
                  setConfirmDelete(false);
                }}
              >
                Delete
              </button>
              <button
                type="button"
                className="sidebar-button"
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="sidebar-section">
        <h2>Previous chats</h2>
        {threads.isLoading && <p className="muted">Loading…</p>}
        {threads.error && <p className="error-text">{(threads.error as Error).message}</p>}
        <ul className="thread-list">
          {threads.data?.threads.map((thread) => (
            <li key={thread.thread_id}>
              <button
                type="button"
                className={`thread-item${thread.thread_id === currentThreadId ? " selected" : ""}`}
                disabled={thread.thread_id === currentThreadId}
                onClick={() => onSelectThread(thread.thread_id)}
              >
                {thread.title}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <p className="api-base muted">API: {API_BASE_URL}</p>
    </aside>
  );
}
