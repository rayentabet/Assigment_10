import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createThread, deleteThread, getThreadHistory, listThreads } from "./client";

const THREADS_KEY = ["threads"] as const;
const historyKey = (threadId: string) => ["thread-history", threadId] as const;

export function useThreadsQuery() {
  return useQuery({ queryKey: THREADS_KEY, queryFn: listThreads });
}

export function useThreadHistoryQuery(threadId: string | null) {
  return useQuery({
    queryKey: historyKey(threadId ?? ""),
    queryFn: () => getThreadHistory(threadId as string),
    enabled: threadId !== null,
  });
}

export function useCreateThreadMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createThread,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: THREADS_KEY });
    },
  });
}

export function useDeleteThreadMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteThread,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: THREADS_KEY });
    },
  });
}
