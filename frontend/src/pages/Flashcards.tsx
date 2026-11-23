import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Markdown } from "../components/Markdown";
import { relativeFromNow } from "../lib/format";

const RATINGS = [
  { value: 1, label: "Again", hint: "Forgot it" },
  { value: 2, label: "Hard", hint: "Got it, with effort" },
  { value: 3, label: "Good", hint: "Got it" },
  { value: 4, label: "Easy", hint: "Instant" },
] as const;

export function Flashcards() {
  const [params] = useSearchParams();
  const scope = { packId: params.get("packId") ?? undefined, exam: params.get("exam") ?? undefined };
  const qc = useQueryClient();
  // Snapshot the queue once per session so cards don't reshuffle under you mid-review.
  const queue = useQuery({
    queryKey: ["study-queue", scope],
    queryFn: () => api.studyQueue(scope),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const [pos, setPos] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [requeue, setRequeue] = useState<string[]>([]);
  const [lastDue, setLastDue] = useState<string | null>(null);
  const [tally, setTally] = useState({ reviewed: 0, again: 0 });
  const shownAt = useRef(Date.now());

  const cards = queue.data?.cards ?? [];
  // Cards rated "Again" come back at the end of this session.
  const order = [...cards.map((c) => c.id), ...requeue];
  const card = cards.find((c) => c.id === order[pos]);

  const review = useMutation({
    mutationFn: ({ itemId, rating }: { itemId: string; rating: number }) =>
      api.review(itemId, rating, Date.now() - shownAt.current),
    onSuccess: (r, v) => {
      setLastDue(r.due);
      setTally((t) => ({ reviewed: t.reviewed + 1, again: t.again + (v.rating === 1 ? 1 : 0) }));
      if (v.rating === 1) setRequeue((q) => [...q, v.itemId]);
      setPos((p) => p + 1);
      setFlipped(false);
      shownAt.current = Date.now();
      qc.invalidateQueries({ queryKey: ["packs"] });
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!card || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.key === " " || e.key === "Enter") && !flipped) {
        e.preventDefault();
        setFlipped(true);
      } else if (flipped && /^[1-4]$/.test(e.key) && !review.isPending) {
        review.mutate({ itemId: card.id, rating: Number(e.key) });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (queue.isPending) return <p className="page muted">Loading cards…</p>;
  if (queue.error) return <p className="page error">{queue.error.message}</p>;

  if (!card) {
    return (
      <div className="page empty">
        <h1>{tally.reviewed ? "Session done" : "Nothing to review right now"}</h1>
        <p>
          {tally.reviewed
            ? `You reviewed ${tally.reviewed} card${tally.reviewed === 1 ? "" : "s"}${tally.again ? `, ${tally.again} marked Again` : ""}.`
            : "Every card in this set is scheduled for later."}
          {lastDue && ` The last card comes back ${relativeFromNow(lastDue)}.`}
        </p>
        <div className="question-actions">
          <button
            className="btn primary"
            onClick={() => {
              setPos(0);
              setRequeue([]);
              setTally({ reviewed: 0, again: 0 });
              qc.invalidateQueries({ queryKey: ["study-queue"] });
            }}
          >
            Check for more cards
          </button>
          <Link className="btn" to="/">
            Back to library
          </Link>
        </div>
      </div>
    );
  }

  const left = order.length - pos;
  return (
    <div className="page flashcards">
      <p className="question-meta">
        {left} card{left === 1 ? "" : "s"} left in this session
        {card.topics?.length ? `. ${card.topics.map((t) => queue.data.topicNames[t] ?? t).join(", ")}` : ""}
      </p>
      <article className={`card ${flipped ? "is-flipped" : ""}`}>
        <Markdown className="prompt">{card.prompt}</Markdown>
        {flipped ? (
          <div className="card-answer">
            <Markdown>{card.answer.text ?? ""}</Markdown>
            {card.explanation && <Markdown className="muted">{card.explanation}</Markdown>}
          </div>
        ) : (
          <button className="btn primary reveal" onClick={() => setFlipped(true)} autoFocus>
            Show answer
          </button>
        )}
      </article>
      {flipped && (
        <div className="ratings" role="group" aria-label="How well did you remember?">
          {RATINGS.map((r) => (
            <button
              key={r.value}
              className={`btn rating rating-${r.value}`}
              disabled={review.isPending}
              onClick={() => review.mutate({ itemId: card.id, rating: r.value })}
            >
              <span>{r.label}</span>
              <span className="rating-hint">
                {r.hint}, key {r.value}
              </span>
            </button>
          ))}
        </div>
      )}
      {review.error && <p className="error">{review.error.message}</p>}
      <p className="hint muted">Space shows the answer. Keys 1 to 4 rate it.</p>
    </div>
  );
}
