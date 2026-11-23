import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { api, type Attempt, type AttemptEntry, type Confidence, type ResponseIn } from "../api";
import { Bubbles, marksFor } from "../components/Bubbles";
import { CONFIDENCE_KEYS, ConfidencePicker } from "../components/Confidence";
import { Feedback } from "../components/Feedback";
import { TutorHelp } from "../components/Tutor";
import { Markdown } from "../components/Markdown";
import { Timer } from "../components/Timer";

export function QuizRunner() {
  const { id = "" } = useParams();
  const attempt = useQuery({ queryKey: ["attempt", id], queryFn: () => api.attempt(id) });

  if (attempt.isPending) return <p className="page muted">Loading quiz…</p>;
  if (attempt.error) return <p className="page error">{attempt.error.message}</p>;
  if (attempt.data.submittedAt) return <Navigate to={`/attempt/${id}/review`} replace />;
  return <Runner attempt={attempt.data} />;
}

function firstOpenIndex(a: Attempt) {
  const i = a.items.findIndex((e) => !e.response?.answered);
  return i === -1 ? 0 : i;
}

function Runner({ attempt }: { attempt: Attempt }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const isExam = attempt.mode === "exam";
  const [index, setIndex] = useState(() => firstOpenIndex(attempt));
  const [drafts, setDrafts] = useState<Record<string, string[]>>({});
  const [sureness, setSureness] = useState<Record<string, Confidence>>({});
  const [confirming, setConfirming] = useState(false);
  const shownAt = useRef(Date.now());

  const entry = attempt.items[index];
  const item = entry.item;
  const saved = entry.response?.choiceIds ?? [];
  const selected = drafts[item.id] ?? saved;
  const confidence = sureness[item.id] ?? (entry.response?.confidence as Confidence | null) ?? null;
  const revealed = !!entry.revealed;
  const multi = item.type === "mcq_multi";
  const isLast = index === attempt.items.length - 1;

  useEffect(() => {
    shownAt.current = Date.now();
  }, [index]);

  const putEntry = useCallback(
    (e: AttemptEntry) =>
      qc.setQueryData<Attempt>(["attempt", attempt.id], (old) =>
        old && { ...old, items: old.items.map((x) => (x.item.id === e.item.id ? e : x)) },
      ),
    [qc, attempt.id],
  );

  const save = useMutation({
    scope: { id: `attempt-${attempt.id}` }, // run saves in order, never in parallel
    mutationFn:({ itemId, body }: { itemId: string; body: ResponseIn }) =>
      api.saveResponse(attempt.id, itemId, body),
    onSuccess: (e) => {
      putEntry(e);
      setDrafts(({ [e.item.id]: _done, ...rest }) => rest);
    },
    onError: () => qc.invalidateQueries({ queryKey: ["attempt", attempt.id] }), // e.g. time ran out
  });

  const submit = useMutation({
    mutationFn: () => api.submit(attempt.id),
    onSuccess: (a) => {
      qc.setQueryData(["attempt", attempt.id], a);
      qc.invalidateQueries({ queryKey: ["packs"] });
      qc.invalidateQueries({ queryKey: ["due-questions"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/attempt/${attempt.id}/review`, { replace: true });
    },
  });

  const elapsed = () => {
    const ms = Date.now() - shownAt.current;
    shownAt.current = Date.now();
    return ms;
  };

  const toggle = (choiceId: string) => {
    if (revealed) return;
    const next = multi
      ? selected.includes(choiceId)
        ? selected.filter((c) => c !== choiceId)
        : [...selected, choiceId].sort()
      : [choiceId];
    if (isExam) {
      // Exam answers save as you go and can be changed until you submit.
      setDrafts((d) => ({ ...d, [item.id]: next }));
      save.mutate({ itemId: item.id, body: { choiceIds: next, timeMs: elapsed() } });
    } else {
      setDrafts((d) => ({ ...d, [item.id]: next }));
    }
  };

  const check = () => {
    if (!selected.length || revealed) return;
    save.mutate({
      itemId: item.id,
      body: { choiceIds: selected, timeMs: elapsed(), ...(confidence ? { confidence } : {}) },
    });
  };

  const rate = (c: Confidence) => {
    if (revealed) return;
    setSureness((s) => ({ ...s, [item.id]: c }));
    // Exam answers save as you go; in practice the rating goes with "Check answer".
    if (isExam) save.mutate({ itemId: item.id, body: { confidence: c } });
  };

  const go = (i: number) => setIndex(Math.max(0, Math.min(attempt.items.length - 1, i)));
  const flag = () => save.mutate({ itemId: item.id, body: { flagged: !entry.response?.flagged } });

  const primary = () => {
    if (isExam) return isLast ? setConfirming(true) : go(index + 1);
    if (!revealed) return check();
    return isLast ? submit.mutate() : go(index + 1);
  };

  // Keyboard: letters/numbers pick choices, Enter continues, F flags, arrows move (exam).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" && (t as HTMLInputElement).type === "number") return;
      if (t.tagName === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
      const choices = item.choices ?? [];
      const key = e.key.toUpperCase();
      const byLetter = choices.find((c) => c.id === key);
      const byNumber = /^[1-9]$/.test(e.key) ? choices[Number(e.key) - 1] : undefined;
      if (byLetter || byNumber) {
        e.preventDefault();
        toggle((byLetter ?? byNumber)!.id);
      } else if (CONFIDENCE_KEYS[key]) {
        rate(CONFIDENCE_KEYS[key]);
      } else if (e.key === "Enter" && (t.tagName !== "BUTTON" || t.classList.contains("confidence-opt"))) {
        e.preventDefault();
        primary();
      } else if (key === "F") {
        flag();
      } else if (isExam && e.key === "ArrowRight") {
        go(index + 1);
      } else if (isExam && e.key === "ArrowLeft") {
        go(index - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const answeredCount = attempt.items.filter((e) => e.response?.answered).length;
  const flaggedCount = attempt.items.filter((e) => e.response?.flagged).length;
  const marks = useMemo(
    () => (revealed && item.choices ? marksFor(item.choices, saved, item.answer?.choiceIds ?? []) : undefined),
    [revealed, item, saved],
  );

  return (
    <div className={`page runner ${isExam ? "is-exam" : "is-practice"}`}>
      <header className="runner-head">
        <div>
          <h1>{attempt.name}</h1>
          <p className="muted">
            {isExam ? "Timed exam. Answers are checked when you submit." : "Practice. Each answer is checked as you go."}
          </p>
        </div>
        {isExam && attempt.deadlineAt && (
          <Timer
            deadline={attempt.deadlineAt}
            serverTime={attempt.serverTime}
            onExpire={() => qc.invalidateQueries({ queryKey: ["attempt", attempt.id] })}
          />
        )}
      </header>

      <div className="runner-body">
        <nav className="sheet" aria-label="Questions">
          <p className="sheet-label">
            {answeredCount} of {attempt.total} answered
            {flaggedCount > 0 && `, ${flaggedCount} flagged`}
          </p>
          <ol>
            {attempt.items.map((e, i) => {
              const state = !e.revealed
                ? e.response?.answered
                  ? "answered"
                  : "open"
                : e.response?.correct
                  ? "correct"
                  : "wrong";
              return (
                <li key={e.item.id}>
                  <button
                    className={`sheet-cell is-${state} ${i === index ? "is-current" : ""} ${e.response?.flagged ? "is-flagged" : ""}`}
                    aria-current={i === index ? "step" : undefined}
                    aria-label={`Question ${i + 1}, ${state}${e.response?.flagged ? ", flagged" : ""}`}
                    onClick={() => go(i)}
                    disabled={!isExam && !e.revealed && i > firstOpenIndex(attempt)}
                  >
                    {i + 1}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        <article className="question">
          <p className="question-meta">
            Question {index + 1} of {attempt.total}
            {multi && `. Choose ${item.answer?.choiceIds?.length ?? "all that apply"}.`}
            {entry.response?.flagged && <span className="flag-note"> Flagged for review</span>}
          </p>
          {item.missing ? (
            <p className="error">This question was removed from its pack after the quiz started.</p>
          ) : (
            <>
              <Markdown className="prompt">{item.prompt}</Markdown>
              {item.choices && (
                <Bubbles
                  name={`q-${item.id}`}
                  choices={item.choices}
                  selected={selected}
                  multi={multi}
                  disabled={revealed}
                  marks={marks}
                  rationales={revealed ? item.choiceRationales : undefined}
                  onToggle={toggle}
                />
              )}
              <ConfidencePicker value={confidence} onChange={rate} disabled={revealed} />
              {revealed && !isExam && (
                <Feedback item={item} correct={entry.response?.correct ?? false}>
                  <TutorHelp key={item.id} attemptId={attempt.id} item={item} response={entry.response} />
                </Feedback>
              )}
            </>
          )}

          {save.error && <p className="error">{save.error.message}</p>}

          <div className="question-actions">
            {isExam && (
              <button className="btn" onClick={() => go(index - 1)} disabled={index === 0}>
                Previous
              </button>
            )}
            <button className="btn quiet" onClick={flag} aria-pressed={!!entry.response?.flagged}>
              {entry.response?.flagged ? "Unflag" : "Flag for review"}
            </button>
            <button
              className="btn primary"
              onClick={primary}
              disabled={(!isExam && !revealed && !selected.length) || save.isPending || submit.isPending}
            >
              {isExam
                ? isLast
                  ? "Review and submit"
                  : "Next question"
                : !revealed
                  ? "Check answer"
                  : isLast
                    ? "Finish and see results"
                    : "Next question"}
            </button>
          </div>
          <p className="hint muted">
            Keys: A–{item.choices?.at(-1)?.id ?? "D"} to choose, G/U/S for guessing, unsure or sure, Enter to {isExam ? "move on" : "check and continue"}, F
            to flag{isExam && ", arrows to move"}.
          </p>
        </article>
      </div>

      {(confirming || (isExam && submit.isPending)) && (
        <div className="confirm" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="confirm-box">
            <h2 id="confirm-title">Submit this exam?</h2>
            <p>
              {attempt.total - answeredCount > 0
                ? `${attempt.total - answeredCount} question${attempt.total - answeredCount === 1 ? " is" : "s are"} unanswered and will count as wrong.`
                : "Every question has an answer."}
              {flaggedCount > 0 && ` ${flaggedCount} ${flaggedCount === 1 ? "is" : "are"} flagged for review.`}
            </p>
            <div className="question-actions">
              <button className="btn" onClick={() => setConfirming(false)} autoFocus>
                Keep working
              </button>
              <button className="btn primary" onClick={() => submit.mutate()} disabled={submit.isPending}>
                Submit exam
              </button>
            </div>
            {submit.error && <p className="error">{submit.error.message}</p>}
          </div>
        </div>
      )}

      {!isExam && (
        <p className="runner-foot">
          <button className="link" onClick={() => submit.mutate()} disabled={submit.isPending}>
            End practice now and see results
          </button>
        </p>
      )}
    </div>
  );
}
