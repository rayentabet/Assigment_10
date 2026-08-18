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
          <h1>Robotics Multi-Agent Assistant</h1>
          <p className="muted">FastAPI + LangGraph + A2A Component Manager</p>
        </header>
        <ChatPanel conversation={conversation} />
      </main>
      <ActivityPanel conversation={conversation} />
    </div>
  );
}

export default App;
