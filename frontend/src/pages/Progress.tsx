import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type AttemptCreate, type ExamStats } from "../api";
import { MasteryBar, ScoreScale, Sparkline, TrendChart } from "../components/Charts";
import { CONFIDENCE_LABELS } from "../components/Confidence";
import { isWebUrl } from "../components/Feedback";
import { percent } from "../lib/format";
import { STATUS_LABEL, listNames, readinessAdvice, weightPercent } from "../lib/progress";

export function Progress() {
  const exams = useQuery({ queryKey: ["exams"], queryFn: api.exams });
  const [params, setParams] = useSearchParams();

  if (exams.isPending) return <p className="page muted">Loading progress…</p>;
  if (exams.error) return <p className="page error">{exams.error.message}</p>;
  const withQuestions = exams.data.filter((e) => e.questionCount > 0);
  if (!withQuestions.length)
    return (
      <div className="page empty">
        <h1>No exams with questions yet</h1>
        <p>Progress tracks quiz questions. Add a pack with questions to an exam to see it here.</p>
      </div>
    );
  const current = withQuestions.find((e) => e.exam === params.get("exam")) ?? withQuestions[0];

  return (
    <div className="page progress">
      {withQuestions.length > 1 && (
        <div className="filters" role="tablist" aria-label="Exam">
          {withQuestions.map((e) => (
            <button
              key={e.exam}
              role="tab"
              aria-selected={e.exam === current.exam}
              className={`tab ${e.exam === current.exam ? "is-active" : ""}`}
              onClick={() => setParams({ exam: e.exam })}
            >
              {e.name}
            </button>
          ))}
        </div>
      )}
      <ExamProgress exam={current.exam} />
    </div>
  );
}

function useStart() {
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (body: AttemptCreate) => api.createAttempt(body),
    onSuccess: (a) => navigate(`/attempt/${a.id}`),
  });
}

function ExamProgress({ exam }: { exam: string }) {
  const stats = useQuery({ queryKey: ["stats", exam], queryFn: () => api.examStats(exam) });
  const start = useStart();
  if (stats.isPending) return <p className="muted">Loading progress…</p>;
  if (stats.error) return <p className="error">{stats.error.message}</p>;
  const s = stats.data;
  const r = s.readiness;
  const names = Object.fromEntries(s.topics.map((t) => [t.id, t.name]));
  const weakNames = s.weakTopics.map((t) => names[t] ?? t);

  return (
    <>
      <header className="report">
        <h1>{s.name}</h1>
        {r.answered === 0 ? (
          <div className="report-empty">
            <p>Take a quiz and your estimated exam score shows up here, broken down by topic.</p>
            <button
              className="btn primary"
              disabled={start.isPending}
              onClick={() => start.mutate({ mode: "exam", exam, count: Math.min(20, s.questionCount) })}
            >
              Start a {Math.min(20, s.questionCount)}-question mock exam
            </button>
          </div>
        ) : r.score === null ? (
          <p>{readinessAdvice(s)}</p>
        ) : (
          <div className="report-body">
            <p className="report-line">
              <span className="report-label">Estimated exam score</span>
              <strong className="report-score">{Math.round(r.score * 100)}%</strong>
              <span className={`status tone-${r.status}`}>
                <StatusIcon status={r.status} />
                {STATUS_LABEL[r.status]}
              </span>
            </p>
            <ScoreScale score={r.score} passing={r.passingScore} tone={r.status} />
            <p className="muted">
              {readinessAdvice(s)} Passing is {Math.round(r.passingScore * 100)}%.
              {r.answered >= 20 &&
                ` ${r.answered} answers so far, covering ${Math.round(r.coverage * 100)}% of the exam blueprint.`}
            </p>
          </div>
        )}
        {r.answered > 0 && (
          <div className="question-actions report-actions">
            {s.weakTopics.length > 0 && (
              <button
                className="btn primary"
                disabled={start.isPending}
                onClick={() => start.mutate({ mode: "practice", exam, drill: true, count: 10 })}
              >
                Drill {listNames(weakNames)}
              </button>
            )}
            <span className="muted">Mixes in questions due for review.</span>
          </div>
        )}
        {start.error && <p className="error">{start.error.message}</p>}
      </header>

      {s.topics.length > 0 && <TopicTable s={s} onDrill={(t) => start.mutate({ mode: "practice", exam, drill: true, topics: [t], count: 10 })} busy={start.isPending} />}

      {s.trend.length > 0 && (
        <section className="panel" aria-labelledby="trend-title">
          <h2 id="trend-title">Score per quiz</h2>
          <TrendChart points={s.trend} passing={r.passingScore} />
          <p className="muted note">
            Your last {s.trend.length} quiz{s.trend.length === 1 ? "" : "zes"} on this exam, oldest first. Filled dots are
            timed exams. <Link to="/history">See all in history</Link>.
          </p>
        </section>
      )}

      {r.answered > 0 && <Calibration s={s} onPractice={(ids, name) => start.mutate({ mode: "practice", itemIds: ids, name })} busy={start.isPending} />}

      <section className="panel" aria-labelledby="reading-title">
        <h2 id="reading-title">Reading list from your misses</h2>
        {s.resources.filter((x) => isWebUrl(x.url)).length > 0 ? (
          <ul className="reading-list">
            {s.resources
              .filter((x) => isWebUrl(x.url))
              .map((x) => (
                <li key={x.url}>
                  <a href={x.url} target="_blank" rel="noreferrer">
                    {x.title}
                  </a>
                  <span className="muted">
                    {" "}
                    {x.missCount} missed question{x.missCount === 1 ? "" : "s"}
                    {x.topics.length > 0 && `, ${x.topics.map((t) => names[t] ?? t).join(", ")}`}
                  </span>
                </li>
              ))}
          </ul>
        ) : (
          <p className="muted">
            {s.missedCount === 0
              ? "Nothing to read yet. Links attached to questions you miss collect here."
              : "The questions you've missed don't have reading links yet. They collect here once questions have them."}
          </p>
        )}
        {s.resources.length > 0 && s.missedWithoutResources > 0 && (
          <p className="muted note">
            {s.missedWithoutResources} missed question{s.missedWithoutResources === 1 ? " has" : "s have"} no links.
          </p>
        )}
      </section>
    </>
  );
}

function StatusIcon({ status }: { status: string }) {
  // Shape as well as colour, so the status never relies on colour alone.
  const d =
    status === "on_track"
      ? "M3 8.5l3 3 7-7"
      : status === "below"
        ? "M4 4l8 8M12 4l-8 8"
        : status === "borderline"
          ? "M3 8h10"
          : "M8 4v5M8 11.5v.5";
  return (
    <svg className="status-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function TopicTable({ s, onDrill, busy }: { s: ExamStats; onDrill: (topic: string) => void; busy: boolean }) {
  const passing = s.readiness.passingScore;
  const rows = [...s.topics].sort((a, b) => a.mastery - b.mastery);
  return (
    <section className="panel" aria-labelledby="topics-title">
      <h2 id="topics-title">Topics, weakest first</h2>
      <div className="table-wrap">
        <table className="topic-table">
          <thead>
            <tr>
              <th scope="col">Topic</th>
              <th scope="col" className="num">Share of exam</th>
              <th scope="col">Mastery</th>
              <th scope="col">Recent quizzes</th>
              <th scope="col" className="num">Questions seen</th>
              <th scope="col"><span className="visually-hidden">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <th scope="row">{t.name}</th>
                <td className="num">{weightPercent(t.weight) != null ? `${weightPercent(t.weight)}%` : "–"}</td>
                <td>
                  <span className="mastery">
                    <MasteryBar value={t.answered ? t.mastery : 0} passing={passing} />
                    <span className="num">{t.answered ? `${Math.round(t.mastery * 100)}%` : "not tried"}</span>
                  </span>
                </td>
                <td>
                  <Sparkline points={t.trend} passing={passing} />
                </td>
                <td className="num">
                  {t.seen} of {t.itemCount}
                </td>
                <td>
                  <button className="btn" disabled={busy || t.itemCount === 0} onClick={() => onDrill(t.id)}>
                    Drill<span className="visually-hidden"> {t.name}</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted note">
        Mastery weighs your latest answers most, gives half credit for correct guesses, and starts at 50% before
        you've tried a topic. The tick marks the passing line.
        {s.untopicedCount > 0 &&
          ` ${s.untopicedCount} question${s.untopicedCount === 1 ? " has" : "s have"} no topic yet, so they count toward your score per quiz but not toward mastery.`}
      </p>
    </section>
  );
}

function Calibration({ s, onPractice, busy }: { s: ExamStats; onPractice: (ids: string[], name: string) => void; busy: boolean }) {
  const c = s.calibration;
  const rated = c.levels.reduce((n, l) => n + l.total, 0);
  return (
    <section className="panel" aria-labelledby="calibration-title">
      <h2 id="calibration-title">How well you judge your answers</h2>
      {rated === 0 ? (
        <p className="muted">
          Pick Guessing, Unsure or Sure as you answer (keys G, U, S). It shows which right answers were luck and which
          wrong ones you were confident about.
        </p>
      ) : (
        <>
          <ul className="calibration">
            {c.levels
              .filter((l) => l.total > 0)
              .map((l) => (
                <li key={l.confidence}>
                  <span className="cal-label">When {CONFIDENCE_LABELS[l.confidence].toLowerCase()}</span>
                  <span className="cal-value">
                    right {l.correct} of {l.total} ({percent(l.correct, l.total)}%)
                  </span>
                </li>
              ))}
          </ul>
          {c.unrated > 0 && <p className="muted note">{c.unrated} answers weren't rated.</p>}
        </>
      )}
      {(c.confidentlyWrong.length > 0 || c.luckyGuesses.length > 0) && (
        <div className="question-actions">
          {c.confidentlyWrong.length > 0 && (
            <button className="btn" disabled={busy} onClick={() => onPractice(c.confidentlyWrong, "Sure but wrong")}>
              Practice sure-but-wrong<span className="count">{c.confidentlyWrong.length}</span>
            </button>
          )}
          {c.luckyGuesses.length > 0 && (
            <button className="btn" disabled={busy} onClick={() => onPractice(c.luckyGuesses, "Lucky guesses")}>
              Practice lucky guesses<span className="count">{c.luckyGuesses.length}</span>
            </button>
          )}
        </div>
      )}
    </section>
  );
}
