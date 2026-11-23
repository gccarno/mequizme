import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Attempt, type AttemptCreate } from "../api";
import { Bubbles, marksFor } from "../components/Bubbles";
import { Feedback } from "../components/Feedback";
import { Markdown } from "../components/Markdown";
import { formatDuration, percent } from "../lib/format";

type Filter = "all" | "missed" | "flagged";

export function AttemptReview() {
  const { id = "" } = useParams();
  const attempt = useQuery({ queryKey: ["attempt", id], queryFn: () => api.attempt(id) });
  if (attempt.isPending) return <p className="page muted">Loading results…</p>;
  if (attempt.error) return <p className="page error">{attempt.error.message}</p>;
  if (!attempt.data.submittedAt)
    return (
      <div className="page">
        <p>This quiz is still in progress.</p>
        <Link className="btn primary" to={`/attempt/${id}`}>
          Continue quiz
        </Link>
      </div>
    );
  return <Review attempt={attempt.data} />;
}

export function topicBreakdown(a: Attempt) {
  const rows = new Map<string, { name: string; correct: number; total: number }>();
  for (const e of a.items) {
    const topics = e.item.topics?.length ? e.item.topics : ["_none"];
    for (const t of topics) {
      const row = rows.get(t) ?? { name: a.topicNames[t] ?? "No topic yet", correct: 0, total: 0 };
      row.total += 1;
      row.correct += e.response?.correct ? 1 : 0;
      rows.set(t, row);
    }
  }
  return [...rows.values()].sort((x, y) => x.correct / x.total - y.correct / y.total);
}

function Review({ attempt }: { attempt: Attempt }) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>(() => (attempt.score === attempt.total ? "all" : "missed"));
  const retake = useMutation({
    mutationFn: (body: AttemptCreate) => api.createAttempt(body),
    onSuccess: (a) => navigate(`/attempt/${a.id}`),
  });

  const missed = attempt.items.filter((e) => !e.response?.correct);
  const flagged = attempt.items.filter((e) => e.response?.flagged);
  const shown = { all: attempt.items, missed, flagged }[filter];
  const score = attempt.score ?? 0;
  const took = new Date(attempt.submittedAt!).getTime() - new Date(attempt.startedAt).getTime();
  const topics = useMemo(() => topicBreakdown(attempt), [attempt]);

  return (
    <div className="page review">
      <header className="review-head">
        <h1>{attempt.name}</h1>
        <p className="result">
          <strong>
            {score} of {attempt.total} correct
          </strong>{" "}
          ({percent(score, attempt.total)}%) in {formatDuration(took)}
          {attempt.mode === "exam" ? ", timed" : ", practice"}.
        </p>
        <div className="question-actions">
          {missed.length > 0 && (
            <button
              className="btn primary"
              disabled={retake.isPending}
              onClick={() =>
                retake.mutate({
                  mode: "practice",
                  itemIds: missed.map((e) => e.item.id),
                  name: `Missed from ${attempt.name}`,
                })
              }
            >
              Retake {missed.length} missed
            </button>
          )}
          <button
            className="btn"
            disabled={retake.isPending}
            onClick={() =>
              retake.mutate({
                mode: attempt.mode,
                itemIds: attempt.items.map((e) => e.item.id),
                name: attempt.name,
                shuffle: true,
              })
            }
          >
            Retake all, shuffled
          </button>
          <Link className="btn quiet" to="/">
            Back to library
          </Link>
        </div>
        {retake.error && <p className="error">{retake.error.message}</p>}
        {missed.some((e) => !e.item.explanation) && (
          <p className="muted note">
            Some questions have no explanation or reading links yet. Add them to the pack file, or generate drafts
            once the tutor features are set up.
          </p>
        )}
      </header>

      {topics.length > 1 && (
        <section className="topics" aria-labelledby="topics-title">
          <h2 id="topics-title">By topic, weakest first</h2>
          <ul>
            {topics.map((t) => (
              <li key={t.name}>
                <span className="topic-name">{t.name}</span>
                <span className="topic-bar" aria-hidden="true">
                  <span style={{ width: `${percent(t.correct, t.total)}%` }} />
                </span>
                <span className="topic-score">
                  {t.correct}/{t.total}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="filters" role="tablist" aria-label="Show questions">
        {(
          [
            ["missed", `Missed (${missed.length})`],
            ["flagged", `Flagged (${flagged.length})`],
            ["all", `All (${attempt.items.length})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={filter === key}
            className={`tab ${filter === key ? "is-active" : ""}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {shown.length === 0 && (
        <p className="muted">{filter === "missed" ? "Nothing missed. Every answer was correct." : "No flagged questions."}</p>
      )}
      <ol className="review-list">
        {shown.map((e) => {
          const n = attempt.items.indexOf(e) + 1;
          const picked = e.response?.choiceIds ?? [];
          return (
            <li key={e.item.id} className="review-item">
              <p className="question-meta">
                Question {n}
                {!e.response?.answered && ". Not answered"}
                {e.response?.flagged && <span className="flag-note"> Flagged</span>}
                {e.item.topics?.length ? `. ${e.item.topics.map((t) => attempt.topicNames[t] ?? t).join(", ")}` : ""}
              </p>
              {e.item.missing ? (
                <p className="error">This question was removed from its pack.</p>
              ) : (
                <>
                  <Markdown className="prompt">{e.item.prompt}</Markdown>
                  {e.item.choices && (
                    <Bubbles
                      name={`r-${e.item.id}`}
                      choices={e.item.choices}
                      selected={picked}
                      multi={e.item.type === "mcq_multi"}
                      disabled
                      marks={marksFor(e.item.choices, picked, e.item.answer?.choiceIds ?? [])}
                      rationales={e.item.choiceRationales}
                    />
                  )}
                  <Feedback item={e.item} correct={!!e.response?.correct} />
                </>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
