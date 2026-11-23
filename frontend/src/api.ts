import type { Item, Topic } from "./types/studypack";

export type { Item, Topic };

export interface PackSummary {
  id: string;
  name: string;
  description: string;
  exam: string | null;
  path: string;
  itemCount: number;
  types: Record<string, number>;
  quizzes: { id: string; name: string; count: number; timeLimitSec: number | null }[];
  dueCount: number;
  newCount: number;
  lastAttempt: { id: string; score: number; total: number; submitted_at: string; mode: string } | null;
}

export interface ExamSummary {
  exam: string;
  name: string;
  topics: Topic[];
  packIds: string[];
  questionCount: number;
  cardCount: number;
}

export interface ResponseView {
  choiceIds: string[] | null;
  text: string | null;
  correct: boolean | null;
  flagged: boolean;
  confidence: number | null;
  timeMs: number | null;
  answered: boolean;
}

/** An item as served inside an attempt. Answer fields are absent until revealed. */
export type AttemptItem = Item & { packId?: string; packName?: string; missing?: boolean };

export interface AttemptEntry {
  item: AttemptItem;
  revealed?: boolean;
  response: ResponseView | null;
}

export interface AttemptSummary {
  id: string;
  name: string;
  mode: "practice" | "exam";
  packId: string | null;
  quizId: string | null;
  exam: string | null;
  startedAt: string;
  deadlineAt: string | null;
  submittedAt: string | null;
  score: number | null;
  total: number;
}

export interface Attempt extends AttemptSummary {
  serverTime: string;
  topicNames: Record<string, string>;
  items: AttemptEntry[];
}

export interface AttemptCreate {
  mode: "practice" | "exam";
  packId?: string;
  quizId?: string;
  exam?: string;
  itemIds?: string[];
  topics?: string[];
  count?: number;
  timeLimitSec?: number;
  shuffle?: boolean;
  name?: string;
}

export interface ResponseIn {
  choiceIds?: string[];
  text?: string;
  flagged?: boolean;
  confidence?: number;
  timeMs?: number;
}

export interface StudyQueue {
  dueCount: number;
  newCount: number;
  topicNames: Record<string, string>;
  cards: Item[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const qs = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  packs: () => request<PackSummary[]>("/api/packs"),
  exams: () => request<ExamSummary[]>("/api/exams"),
  attempts: () => request<AttemptSummary[]>("/api/attempts"),
  attempt: (id: string) => request<Attempt>(`/api/attempts/${id}`),
  createAttempt: (body: AttemptCreate) =>
    request<Attempt>("/api/attempts", { method: "POST", body: JSON.stringify(body) }),
  saveResponse: (attemptId: string, itemId: string, body: ResponseIn) =>
    request<AttemptEntry>(`/api/attempts/${attemptId}/responses/${itemId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  submit: (attemptId: string) => request<Attempt>(`/api/attempts/${attemptId}/submit`, { method: "POST" }),
  deleteAttempt: (attemptId: string) => request<void>(`/api/attempts/${attemptId}`, { method: "DELETE" }),
  studyQueue: (params: { packId?: string; exam?: string }) =>
    request<StudyQueue>(`/api/study/queue${qs(params)}`),
  review: (itemId: string, rating: number, durationMs?: number) =>
    request<{ itemId: string; due: string }>("/api/study/review", {
      method: "POST",
      body: JSON.stringify({ itemId, rating, durationMs }),
    }),
  dueQuestions: (params: { packId?: string; exam?: string }) =>
    request<{ count: number; itemIds: string[] }>(`/api/study/due-questions${qs(params)}`),
};
