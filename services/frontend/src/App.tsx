import { useEffect, useRef, useState } from "react";

import { createThread, getThreadHistory } from "./api/client";
import { useDeleteThreadMutation, useThreadsQuery } from "./api/hooks";
import "./App.css";
import { ActivityPanel } from "./components/ActivityPanel/ActivityPanel";
import { ChatPanel } from "./components/ChatPanel/ChatPanel";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { useConversation } from "./hooks/useConversation";

const STORAGE_KEY = "robotics-agent-thread-id";

function App() {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [initError, setInitError] = useState<string | null>(null);
  const hasStartedInit = useRef(false);
  const threads = useThreadsQuery();
  const deleteThreadMutation = useDeleteThreadMutation();
  const conversation = useConversation(threadId);

  function selectThread(id: string) {
    localStorage.setItem(STORAGE_KEY, id);
    setThreadId(id);
  }

  async function handleNewChat() {
    try {
      const response = await createThread();
      selectThread(response.thread_id);
    } catch (err) {
      setInitError(err instanceof Error ? err.message : String(err));
    }
  }

  // Reuse the last thread across page reloads (React state alone doesn't
  // survive a refresh) instead of spawning a new empty thread every time.
  // The ref guard matters because React StrictMode intentionally
  // double-invokes effects in development; without it this creates two
  // threads on first load, since both invocations see threadId === null
  // before either async call resolves.
  useEffect(() => {
    if (hasStartedInit.current) return;
    hasStartedInit.current = true;

    async function ensureThread() {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        try {
          await getThreadHistory(stored);
          setThreadId(stored);
          return;
        } catch {
          localStorage.removeItem(STORAGE_KEY);
        }
      }
      const response = await createThread();
      selectThread(response.thread_id);
    }

    ensureThread().catch((err) =>
      setInitError(err instanceof Error ? err.message : String(err)),
    );
    // Intentionally empty: this must run exactly once per mount, guarded by
    // hasStartedInit above rather than by a dependency array.
  }, []);

  async function handleDeleteThread(id: string) {
    await deleteThreadMutation.mutateAsync(id);
    const remaining = threads.data?.threads.filter((thread) => thread.thread_id !== id) ?? [];
    if (remaining.length > 0) {
      selectThread(remaining[0].thread_id);
    } else {
      await handleNewChat();
    }
  }

  if (initError) {
    return <p className="error-text startup-error">{initError}</p>;
  }

  return (
    <div className="app-layout">
      <Sidebar
        currentThreadId={threadId}
        onSelectThread={selectThread}
        onNewChat={handleNewChat}
        onDeleteThread={handleDeleteThread}
        isDeleting={deleteThreadMutation.isPending}
      />
      <main className="app-main">
        <header className="app-header">
          <div className="app-logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
              <rect x="7" y="3" width="10" height="7" rx="2" stroke="currentColor" strokeWidth="1.6" />
              <circle cx="9.5" cy="6.5" r="1" fill="currentColor" />
              <circle cx="14.5" cy="6.5" r="1" fill="currentColor" />
              <path d="M12 10v2.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <rect x="4" y="12.5" width="16" height="8" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
              <path d="M8 16.5h.01M12 16.5h.01M16 16.5h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </div>
          <div className="app-header-text">
            <h1>Servo</h1>
            <p className="muted">Robotics multi-agent assistant</p>
          </div>
        </header>
        <ChatPanel conversation={conversation} />
      </main>
      <ActivityPanel conversation={conversation} />
    </div>
  );
}

export default App;
