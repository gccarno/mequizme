import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Attempt, type AttemptCreate } from "../api";
import { Bubbles, marksFor } from "../components/Bubbles";
import { CONFIDENCE_LABELS } from "../components/Confidence";
import { Feedback, isWebUrl } from "../components/Feedback";
import { TutorHelp } from "../components/Tutor";
import { Markdown } from "../components/Markdown";
import { formatDuration, percent } from "../lib/format";

type Filter = "all" | "missed" | "flagged" | "lucky" | "sureWrong";

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

/** Reading links from the missed questions, most-cited first. */
export function missedResources(a: Attempt) {
  const rows = new Map<string, { title: string; url: string; count: number }>();
  for (const e of a.items) {
    if (e.response?.correct) continue;
    for (const r of e.item.resources ?? []) {
      if (!isWebUrl(r.url)) continue;
      const row = rows.get(r.url) ?? { title: r.title, url: r.url, count: 0 };
      row.count += 1;
      rows.set(r.url, row);
    }
  }
  return [...rows.values()].sort((x, y) => y.count - x.count || x.title.localeCompare(y.title));
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
  const lucky = attempt.items.filter((e) => e.response?.correct && e.response.confidence === 1);
  const sureWrong = attempt.items.filter((e) => e.response && !e.response.correct && e.response.confidence === 3);
  const shown = { all: attempt.items, missed, flagged, lucky, sureWrong }[filter];
  const reading = useMemo(() => missedResources(attempt), [attempt]);
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

      {reading.length > 0 && (
        <section className="reading" aria-labelledby="reading-title">
          <h2 id="reading-title">Read before you retake</h2>
          <ul>
            {reading.map((r) => (
              <li key={r.url}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
                {r.count > 1 && <span className="muted"> covers {r.count} missed questions</span>}
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
            ...(sureWrong.length ? [["sureWrong", `Sure but wrong (${sureWrong.length})`] as const] : []),
            ...(lucky.length ? [["lucky", `Lucky guesses (${lucky.length})`] as const] : []),
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
        <p className="muted">
          {
            {
              missed: "Nothing missed. Every answer was correct.",
              flagged: "No flagged questions.",
              lucky: "No lucky guesses.",
              sureWrong: "No answers you were sure of turned out wrong.",
              all: "",
            }[filter]
          }
        </p>
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
                {e.response?.confidence ? `. ${CONFIDENCE_LABELS[e.response.confidence as 1 | 2 | 3]}` : ""}
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
                  <Feedback item={e.item} correct={!!e.response?.correct}>
                    <TutorHelp attemptId={attempt.id} item={e.item} response={e.response} />
                  </Feedback>
                </>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
