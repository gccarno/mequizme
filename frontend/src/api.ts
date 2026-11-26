import type { Draft, Item, Resource, Topic } from "./types/studypack";

export type { Draft, Item, Resource, Topic };

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
  drill?: boolean;
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

export type Confidence = 1 | 2 | 3; // guessing, unsure, sure

export interface TrendPoint {
  attemptId: string;
  name: string;
  mode: "practice" | "exam";
  at: string;
  correct: number;
  total: number;
}

export interface TopicStats {
  id: string;
  name: string;
  weight: number | null;
  itemCount: number;
  seen: number;
  answered: number;
  correct: number;
  mastery: number;
  trend: TrendPoint[];
}

export type ReadinessStatus = "early" | "on_track" | "borderline" | "below" | "no_topics";

export interface ExamStats {
  exam: string;
  name: string;
  questionCount: number;
  untopicedCount: number;
  readiness: {
    score: number | null;
    coverage: number;
    answered: number;
    passingScore: number;
    status: ReadinessStatus;
  };
  topics: TopicStats[];
  weakTopics: string[];
  trend: TrendPoint[];
  calibration: {
    levels: { confidence: Confidence; correct: number; total: number }[];
    unrated: number;
    confidentlyWrong: string[];
    luckyGuesses: string[];
  };
  missedCount: number;
  resources: { title: string; url: string; kind?: string; missCount: number; topics: string[] }[];
  missedWithoutResources: number;
  dueCount: number;
}

export type AiStatus =
  | { available: false; reason: string }
  | { available: true; provider: "claude-code" | "api"; model: string; label: string };

export interface AiJob {
  id: string;
  kind: "enrich" | "generate";
  params: { exam?: string; packId?: string; topic?: string; count?: number; focus?: string };
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
  total: number;
  done: number;
  changed: number;
  errors: string[];
  createdAt: string;
  finishedAt: string | null;
}

export type DraftItem = Item & { packId: string; packName: string; exam: string | null };

export interface DraftEdits {
  explanation?: string;
  choiceRationales?: Record<string, string>;
  resources?: { title: string; url: string; kind?: string }[];
  topics?: string[];
  difficulty?: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatContext {
  attemptId?: string;
  itemId?: string;
  exam?: string;
  topic?: string;
}

export interface CloudStatus {
  configured: boolean;
  connected: boolean;
  email: string | null;
  lastSync: string | null;
  lastError: string | null;
  pending: number;
  syncing: boolean;
}

export interface SyncResult {
  pushed: Record<string, number>;
  pulled: Record<string, number>;
  status: CloudStatus;
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
  examStats: (exam: string) => request<ExamStats>(`/api/stats/exams/${encodeURIComponent(exam)}`),
  aiStatus: () => request<AiStatus>("/api/ai/status"),
  enrichPreview: (params: { exam?: string; packId?: string }) =>
    request<{ count: number }>(`/api/ai/enrich/preview${qs(params)}`),
  startEnrich: (body: { exam?: string; packId?: string; itemIds?: string[] }) =>
    request<AiJob>("/api/ai/enrich", { method: "POST", body: JSON.stringify(body) }),
  startGenerate: (body: { exam: string; topic: string; count: number; focus?: string }) =>
    request<AiJob>("/api/ai/generate", { method: "POST", body: JSON.stringify(body) }),
  jobs: () => request<AiJob[]>("/api/ai/jobs"),
  job: (id: string) => request<AiJob>(`/api/ai/jobs/${id}`),
  cancelJob: (id: string) => request<AiJob>(`/api/ai/jobs/${id}/cancel`, { method: "POST" }),
  explainMistake: (attemptId: string, itemId: string, refresh = false) =>
    request<{ text: string; by: string; cached: boolean }>("/api/ai/explain", {
      method: "POST",
      body: JSON.stringify({ attemptId, itemId, refresh }),
    }),
  chat: (messages: ChatMessage[], context: ChatContext) =>
    request<{ reply: string }>("/api/ai/chat", { method: "POST", body: JSON.stringify({ messages, ...context }) }),
  drafts: (exam?: string) =>
    request<{ items: DraftItem[]; topicNames: Record<string, string> }>(`/api/drafts${qs({ exam })}`),
  draftCount: () => request<{ count: number }>("/api/drafts/count"),
  acceptDraft: (itemId: string, edits?: DraftEdits) =>
    request<Item>(`/api/items/${itemId}/accept`, { method: "POST", body: JSON.stringify(edits ?? {}) }),
  rejectDraft: (itemId: string) =>
    request<{ deleted: boolean; item: Item | null }>(`/api/items/${itemId}/reject`, { method: "POST" }),
  cloudStatus: () => request<CloudStatus>("/api/cloud/status"),
  cloudConnect: (idToken: string, refreshToken: string) =>
    request<CloudStatus>("/api/cloud/session", { method: "POST", body: JSON.stringify({ idToken, refreshToken }) }),
  cloudDisconnect: () => request<void>("/api/cloud/session", { method: "DELETE" }),
  cloudSync: () => request<SyncResult>("/api/cloud/sync", { method: "POST" }),
  dueQuestions: (params: { packId?: string; exam?: string }) =>
    request<{ count: number; itemIds: string[] }>(`/api/study/due-questions${qs(params)}`),
};
