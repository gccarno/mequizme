import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AttemptCreate, type ExamSummary, type PackSummary } from "../api";
import { percent } from "../lib/format";

export function Library() {
  const packs = useQuery({ queryKey: ["packs"], queryFn: api.packs });
  const exams = useQuery({ queryKey: ["exams"], queryFn: api.exams });

  if (packs.isPending || exams.isPending) return <p className="muted page">Loading your study packs…</p>;
  if (packs.error || exams.error)
    return (
      <p className="error page">
        Can't reach the study server. Start it with <code>uv run mequizme</code> in <code>backend/</code>, then
        reload.
      </p>
    );
  if (!packs.data.length)
    return (
      <div className="page empty">
        <h1>No study packs yet</h1>
        <p>
          Add pack files to <code>content/</code> (or convert a quiz with <code>studypack convert-md</code>) and
          restart the server.
        </p>
      </div>
    );

  const byExam = new Map<string, PackSummary[]>();
  for (const p of packs.data) {
    const key = p.exam ?? "";
    byExam.set(key, [...(byExam.get(key) ?? []), p]);
  }

  return (
    <div className="page library">
      {[...byExam.entries()].map(([examId, list]) => {
        const exam = exams.data.find((e) => e.exam === examId);
        return (
          <section key={examId} className="exam-block">
            <header className="exam-head">
              <h2>{exam?.name ?? "Other packs"}</h2>
              {exam && <ExamActions exam={exam} packs={list} />}
            </header>
            <ul className="pack-list">
              {list.map((p) => (
                <PackRow key={p.id} pack={p} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function useStartAttempt() {
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (body: AttemptCreate) => api.createAttempt(body),
    onSuccess: (a) => navigate(`/attempt/${a.id}`),
  });
}

function ExamActions({ exam, packs }: { exam: ExamSummary; packs: PackSummary[] }) {
  const start = useStartAttempt();
  const navigate = useNavigate();
  const due = useQuery({ queryKey: ["due-questions", exam.exam], queryFn: () => api.dueQuestions({ exam: exam.exam }) });
  const [count, setCount] = useState(Math.min(45, exam.questionCount));
  const cardsDue = packs.reduce((n, p) => n + p.dueCount, 0);
  const cardsNew = packs.reduce((n, p) => n + p.newCount, 0);

  return (
    <div className="exam-actions">
      {exam.questionCount > 0 && (
        <form
          className="mock-form"
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate({ mode: "exam", exam: exam.exam, count });
          }}
        >
          <label>
            Mock exam with{" "}
            <input
              type="number"
              min={1}
              max={exam.questionCount}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              aria-label="Number of questions"
            />{" "}
            of {exam.questionCount} questions, {count * 2} min
          </label>
          <button className="btn primary" disabled={start.isPending}>
            Start mock exam
          </button>
        </form>
      )}
      <div className="exam-links">
        {exam.cardCount > 0 && (
          <button className="btn" onClick={() => navigate(`/study?exam=${encodeURIComponent(exam.exam)}`)}>
            Study flashcards
            <span className="count">
              {cardsDue} due, {cardsNew} new
            </span>
          </button>
        )}
        {(due.data?.count ?? 0) > 0 && (
          <button
            className="btn"
            onClick={() =>
              start.mutate({ mode: "practice", itemIds: due.data!.itemIds, name: `${exam.name}: questions to review` })
            }
          >
            Review missed questions
            <span className="count">{due.data!.count} due</span>
          </button>
        )}
      </div>
      {start.error && <p className="error">{start.error.message}</p>}
    </div>
  );
}

function PackRow({ pack }: { pack: PackSummary }) {
  const start = useStartAttempt();
  const navigate = useNavigate();
  const questions = (pack.types.mcq_single ?? 0) + (pack.types.mcq_multi ?? 0) + (pack.types.true_false ?? 0) + (pack.types.short_answer ?? 0);
  const cards = (pack.types.flashcard ?? 0) + (pack.types.cloze ?? 0);
  const quiz = pack.quizzes[0];
  const last = pack.lastAttempt;

  return (
    <li className="pack-row">
      <div className="pack-info">
        <h3>{pack.name}</h3>
        <p className="muted">
          {questions > 0 && `${questions} questions`}
          {questions > 0 && cards > 0 && ", "}
          {cards > 0 && `${cards} flashcards`}
          {last && (
            <>
              {". "}
              <Link to={`/attempt/${last.id}/review`}>
                Last score {last.score}/{last.total} ({percent(last.score, last.total)}%)
              </Link>
            </>
          )}
        </p>
      </div>
      <div className="pack-actions">
        {cards > 0 && (
          <button className="btn" onClick={() => navigate(`/study?packId=${pack.id}`)}>
            Flashcards
            {pack.dueCount + pack.newCount > 0 && <span className="count">{pack.dueCount + pack.newCount}</span>}
          </button>
        )}
        {questions > 0 && (
          <>
            <button
              className="btn"
              disabled={start.isPending}
              onClick={() => start.mutate({ mode: "practice", packId: pack.id, quizId: quiz?.id })}
            >
              Practice
            </button>
            <button
              className="btn"
              disabled={start.isPending}
              onClick={() => start.mutate({ mode: "exam", packId: pack.id, quizId: quiz?.id })}
            >
              Timed
            </button>
          </>
        )}
      </div>
      {start.error && <p className="error">{start.error.message}</p>}
    </li>
  );
}
