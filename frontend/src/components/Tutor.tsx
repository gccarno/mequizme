import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AttemptItem, type ChatContext, type ChatMessage, type ResponseView } from "../api";
import { Markdown } from "./Markdown";

/** Whether AI features are on. Hidden everywhere when they aren't. */
export function useAiStatus() {
  return useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus, staleTime: Infinity });
}

const FIELD_NAMES: Record<string, string> = {
  explanation: "explanation",
  choiceRationales: "notes on the wrong choices",
  resources: "links",
  topics: "topic",
  difficulty: "difficulty",
};

export function draftFieldNames(fields: string[]): string[] {
  return fields.map((f) => FIELD_NAMES[f]).filter(Boolean);
}

/** Tells the learner that some of what they're reading hasn't been checked by a person. */
export function DraftNote({ item }: { item: AttemptItem }) {
  const d = item.draft;
  if (!d) return null;
  // Difficulty isn't shown to learners, so don't mention it.
  const names = draftFieldNames(d.fields.filter((f) => f !== "difficulty"));
  return (
    <div className="draft-note">
      {item.status === "draft" ? (
        <p>The AI tutor wrote this question. It hasn't been checked yet.</p>
      ) : (
        names.length > 0 && (
          <p>
            The {names.join(", ")} {names.length === 1 ? "was" : "were"} written by the AI tutor and{" "}
            {names.length === 1 ? "hasn't" : "haven't"} been checked yet. <Link to="/drafts">Review drafts</Link>
          </p>
        )
      )}
      {d.notes && <p className="draft-doubt">{d.notes}</p>}
    </div>
  );
}

/** "Explain my mistake" and "Ask the tutor", under a revealed answer. */
export function TutorHelp({
  attemptId,
  item,
  response,
}: {
  attemptId: string;
  item: AttemptItem;
  response: ResponseView | null;
}) {
  const ai = useAiStatus();
  const [chatOpen, setChatOpen] = useState(false);
  const explain = useMutation({
    mutationFn: (refresh: boolean) => api.explainMistake(attemptId, item.id, refresh),
  });
  if (!ai.data?.available || item.missing) return null;
  const wrong = response?.correct === false && !!response.choiceIds?.length;

  return (
    <div className="tutor">
      <div className="tutor-actions">
        {wrong && !explain.data && (
          <button className="btn" onClick={() => explain.mutate(false)} disabled={explain.isPending}>
            {explain.isPending ? "Asking the tutor…" : "Explain my mistake"}
          </button>
        )}
        {!chatOpen && (
          <button className="btn quiet" onClick={() => setChatOpen(true)}>
            Ask the tutor about this question
          </button>
        )}
      </div>
      {explain.error && <p className="error">{explain.error.message}</p>}
      {explain.data && (
        <section className="tutor-note" aria-label="The tutor's explanation">
          <Markdown>{explain.data.text}</Markdown>
          <p className="tutor-by">
            From the AI tutor ({explain.data.by}).{" "}
            <button className="link" onClick={() => explain.mutate(true)} disabled={explain.isPending}>
              {explain.isPending ? "Rewriting…" : "Explain it differently"}
            </button>
          </p>
        </section>
      )}
      {chatOpen && <TutorChat context={{ attemptId, itemId: item.id }} onClose={() => setChatOpen(false)} />}
    </div>
  );
}

export function TutorChat({
  context,
  onClose,
  placeholder = "Ask about this question…",
}: {
  context: ChatContext;
  onClose?: () => void;
  placeholder?: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const send = useMutation({
    mutationFn: (history: ChatMessage[]) => api.chat(history, context),
    onSuccess: (r) => setMessages((m) => [...m, { role: "assistant", content: r.reply }]),
  });

  function submit() {
    const text = draft.trim();
    if (!text || send.isPending) return;
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setDraft("");
    send.mutate(history);
    input.current?.focus();
  }

  return (
    <section className="chat" aria-label="Chat with the AI tutor">
      {messages.length > 0 && (
        <ol className="chat-log" aria-live="polite">
          {messages.map((m, i) => (
            <li key={i} className={`chat-msg is-${m.role}`}>
              <span className="chat-who">{m.role === "user" ? "You" : "Tutor"}</span>
              {m.role === "user" ? <p>{m.content}</p> : <Markdown>{m.content}</Markdown>}
            </li>
          ))}
          {send.isPending && (
            <li className="chat-msg is-assistant">
              <span className="chat-who">Tutor</span>
              <p className="muted">Thinking…</p>
            </li>
          )}
        </ol>
      )}
      {send.error && <p className="error">{send.error.message}</p>}
      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="visually-hidden" htmlFor={`chat-${context.itemId ?? context.topic ?? "exam"}`}>
          Message to the tutor
        </label>
        <textarea
          id={`chat-${context.itemId ?? context.topic ?? "exam"}`}
          ref={input}
          rows={2}
          value={draft}
          placeholder={placeholder}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="chat-buttons">
          <button className="btn primary" type="submit" disabled={!draft.trim() || send.isPending}>
            Send
          </button>
          {onClose && (
            <button className="btn quiet" type="button" onClick={onClose}>
              Close chat
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
