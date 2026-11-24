import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type AiJob, type DraftEdits, type DraftItem, type ExamSummary } from "../api";
import { isWebUrl } from "../components/Feedback";
import { Markdown } from "../components/Markdown";
import { draftFieldNames, useAiStatus } from "../components/Tutor";
import { jobLine } from "../lib/drafts";

export function Drafts() {
  const exams = useQuery({ queryKey: ["exams"], queryFn: api.exams });
  const all = useQuery({ queryKey: ["drafts", "all"], queryFn: () => api.drafts() });
  const [params, setParams] = useSearchParams();
  if (exams.isPending || all.isPending) return <p className="page muted">Loading…</p>;
  if (exams.error) return <p className="page error">{exams.error.message}</p>;
  const list = exams.data.filter((e) => e.topics.length > 0);
  const waiting = (exam: string) => (all.data?.items ?? []).filter((i) => i.exam === exam).length;
  // Open on the exam with drafts waiting, unless one was picked.
  const current =
    list.find((e) => e.exam === params.get("exam")) ?? list.find((e) => waiting(e.exam) > 0) ?? list[0];

  return (
    <div className="page drafts">
      <h1>AI tutor</h1>
      <p className="lede">
        The tutor fills in explanations and links, and writes new practice questions. Everything it writes waits here
        until you accept it.
      </p>
      {list.length > 1 && (
        <div className="filters" role="tablist" aria-label="Exam">
          {list.map((e) => (
            <button
              key={e.exam}
              role="tab"
              aria-selected={e.exam === current?.exam}
              className={`tab ${e.exam === current?.exam ? "is-active" : ""}`}
              onClick={() => setParams({ exam: e.exam })}
            >
              {e.name}
              {waiting(e.exam) > 0 && (
                <span className="nav-count">
                  {waiting(e.exam)}
                  <span className="visually-hidden"> to review</span>
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {current ? <ExamDrafts exam={current} /> : <p className="muted">Add a pack with exam topics to use the tutor.</p>}
    </div>
  );
}

function ExamDrafts({ exam }: { exam: ExamSummary }) {
  const ai = useAiStatus();
  return (
    <>
      {ai.data?.available === false && (
        <p className="notice">
          {ai.data.reason} You can still review drafts that are already here.
        </p>
      )}
      {ai.data?.available && <Tools exam={exam} />}
      <DraftList exam={exam} />
    </>
  );
}

// --- start jobs -----------------------------------------------------------------------------

function useJobs() {
  const qc = useQueryClient();
  const jobs = useQuery({
    queryKey: ["ai-jobs"],
    queryFn: api.jobs,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 1500 : false),
  });
  // Drafts land while a job runs; refresh the list as progress moves.
  const progress = jobs.data?.map((j) => `${j.id}:${j.done}:${j.status}`).join() ?? "";
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["drafts"] });
    qc.invalidateQueries({ queryKey: ["enrich-preview"] });
    qc.invalidateQueries({ queryKey: ["draft-count"] });
  }, [progress, qc]);
  return jobs;
}

function Tools({ exam }: { exam: ExamSummary }) {
  const qc = useQueryClient();
  const jobs = useJobs();
  const preview = useQuery({
    queryKey: ["enrich-preview", exam.exam],
    queryFn: () => api.enrichPreview({ exam: exam.exam }),
  });
  const started = () => qc.invalidateQueries({ queryKey: ["ai-jobs"] });
  const enrich = useMutation({ mutationFn: () => api.startEnrich({ exam: exam.exam }), onSuccess: started });
  const [topic, setTopic] = useState(exam.topics[0]?.id ?? "");
  const [count, setCount] = useState(5);
  const [focus, setFocus] = useState("");
  const generate = useMutation({
    mutationFn: () => api.startGenerate({ exam: exam.exam, topic, count, focus: focus.trim() || undefined }),
    onSuccess: () => {
      setFocus("");
      started();
    },
  });
  const mine = (jobs.data ?? []).filter((j) => (j.params.exam ?? exam.exam) === exam.exam).slice(0, 4);
  const running = mine.some((j) => j.kind === "enrich" && (j.status === "queued" || j.status === "running"));
  const missing = preview.data?.count ?? 0;

  return (
    <section className="tools" aria-label="Ask the tutor">
      <div className="tool">
        <h2>Fill in explanations</h2>
        {preview.isPending ? (
          <p className="muted">Checking questions…</p>
        ) : missing === 0 ? (
          <p className="muted">Every question in {exam.name} has an explanation, links and a topic.</p>
        ) : (
          <>
            <p>
              {missing} question{missing === 1 ? " is" : "s are"} missing an explanation, notes on the wrong choices,
              links or a topic. The tutor also checks each answer key and flags any it doubts.
            </p>
            <button className="btn primary" disabled={running || enrich.isPending} onClick={() => enrich.mutate()}>
              {running ? "Filling in…" : `Fill in ${missing} question${missing === 1 ? "" : "s"}`}
            </button>
          </>
        )}
        {enrich.error && <p className="error">{enrich.error.message}</p>}
      </div>

      <form
        className="tool"
        onSubmit={(e) => {
          e.preventDefault();
          generate.mutate();
        }}
      >
        <h2>Write new questions</h2>
        <div className="tool-fields">
          <label>
            Topic
            <select value={topic} onChange={(e) => setTopic(e.target.value)}>
              {exam.topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            How many
            <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
              {[3, 5, 10].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="grow">
            <span>
              Focus <span className="muted">(optional)</span>
            </span>
            <input
              type="text"
              value={focus}
              maxLength={300}
              placeholder="e.g. Feature Store lookups, AutoML outputs"
              onChange={(e) => setFocus(e.target.value)}
            />
          </label>
        </div>
        <button className="btn primary" type="submit" disabled={!topic || generate.isPending}>
          Write {count} questions
        </button>
        {generate.error && <p className="error">{generate.error.message}</p>}
      </form>

      {mine.length > 0 && (
        <ul className="jobs" aria-live="polite">
          {mine.map((j) => (
            <JobRow key={j.id} job={j} topicNames={Object.fromEntries(exam.topics.map((t) => [t.id, t.name]))} />
          ))}
        </ul>
      )}
    </section>
  );
}

function JobRow({ job, topicNames }: { job: AiJob; topicNames: Record<string, string> }) {
  const qc = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(job.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-jobs"] }),
  });
  const active = job.status === "queued" || job.status === "running";
  return (
    <li className={`job is-${job.status}`}>
      <span>{jobLine(job, topicNames)}</span>
      {active && job.kind === "enrich" && (
        <progress max={job.total} value={job.done} aria-label="Progress">
          {job.done} of {job.total}
        </progress>
      )}
      {active && job.kind === "enrich" && (
        <button className="btn quiet" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
          Stop
        </button>
      )}
      {job.errors.length > 0 && !active && (
        <details>
          <summary>
            {job.errors.length} problem{job.errors.length === 1 ? "" : "s"}
          </summary>
          <ul>
            {job.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

// --- review drafts --------------------------------------------------------------------------

type Filter = "all" | "doubts" | "new";

function DraftList({ exam }: { exam: ExamSummary }) {
  const qc = useQueryClient();
  const drafts = useQuery({ queryKey: ["drafts", exam.exam], queryFn: () => api.drafts(exam.exam) });
  const [filter, setFilter] = useState<Filter>("all");
  const [confirmAll, setConfirmAll] = useState(false);
  const items = drafts.data?.items ?? [];
  const doubts = items.filter((i) => i.draft?.notes);
  const generated = items.filter((i) => i.status === "draft");
  const shown = filter === "doubts" ? doubts : filter === "new" ? generated : items;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["drafts"] });
    qc.invalidateQueries({ queryKey: ["draft-count"] });
    qc.invalidateQueries({ queryKey: ["enrich-preview"] });
    qc.invalidateQueries({ queryKey: ["exams"] });
    qc.invalidateQueries({ queryKey: ["packs"] });
  };
  const acceptAll = useMutation({
    mutationFn: async (ids: string[]) => {
      for (const id of ids) await api.acceptDraft(id);
    },
    onSettled: () => {
      setConfirmAll(false);
      refresh();
    },
  });

  if (drafts.isPending) return <p className="muted">Loading drafts…</p>;
  if (drafts.error) return <p className="error">{drafts.error.message}</p>;

  return (
    <section className="panel" aria-labelledby="drafts-title">
      <h2 id="drafts-title">To review ({items.length})</h2>
      {items.length === 0 ? (
        <p className="muted">Nothing to review. Drafts from the tutor show up here.</p>
      ) : (
        <>
          <div className="draft-bar">
            {(doubts.length > 0 || generated.length > 0) && (
              <div className="seg" role="group" aria-label="Show">
                {(
                  [
                    ["all", `All (${items.length})`],
                    ...(doubts.length ? [["doubts", `Answer key doubts (${doubts.length})`]] : []),
                    ...(generated.length ? [["new", `New questions (${generated.length})`]] : []),
                  ] as [Filter, string][]
                ).map(([f, label]) => (
                  <button key={f} className="btn quiet" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                    {label}
                  </button>
                ))}
              </div>
            )}
            {shown.length > 1 &&
              (confirmAll ? (
                <span className="confirm-inline">
                  Accept all {shown.length} as written?{" "}
                  <button
                    className="btn primary"
                    disabled={acceptAll.isPending}
                    onClick={() => acceptAll.mutate(shown.map((i) => i.id))}
                  >
                    {acceptAll.isPending ? "Accepting…" : "Accept all"}
                  </button>{" "}
                  <button className="btn quiet" onClick={() => setConfirmAll(false)}>
                    Cancel
                  </button>
                </span>
              ) : (
                <button className="btn" onClick={() => setConfirmAll(true)}>
                  Accept all {shown.length} shown
                </button>
              ))}
          </div>
          {acceptAll.error && <p className="error">{acceptAll.error.message}</p>}
          <ol className="draft-list">
            {shown.map((item) => (
              <DraftCard key={item.id} item={item} topicNames={drafts.data.topicNames} exam={exam} onDone={refresh} />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

interface EditState {
  explanation: string;
  rationales: Record<string, string>;
  resources: { title: string; url: string }[];
  topics: string[];
  difficulty: number | null;
}

function editState(item: DraftItem): EditState {
  return {
    explanation: item.explanation ?? "",
    rationales: { ...(item.choiceRationales ?? {}) },
    resources: (item.resources ?? []).map((r) => ({ title: r.title, url: r.url })),
    topics: [...(item.topics ?? [])],
    difficulty: item.difficulty ?? null,
  };
}

function toEdits(s: EditState): DraftEdits {
  const rationales = Object.fromEntries(Object.entries(s.rationales).filter(([, v]) => v.trim()));
  return {
    explanation: s.explanation.trim(),
    choiceRationales: rationales,
    resources: s.resources.filter((r) => r.title.trim() && isWebUrl(r.url.trim())).map((r) => ({
      title: r.title.trim(),
      url: r.url.trim(),
      kind: "doc",
    })),
    topics: s.topics,
    ...(s.difficulty ? { difficulty: s.difficulty } : {}),
  };
}

function DraftCard({
  item,
  topicNames,
  exam,
  onDone,
}: {
  item: DraftItem;
  topicNames: Record<string, string>;
  exam: ExamSummary;
  onDone: () => void;
}) {
  const [editing, setEditing] = useState<EditState | null>(null);
  const accept = useMutation({
    mutationFn: (edits?: DraftEdits) => api.acceptDraft(item.id, edits),
    onSuccess: onDone,
  });
  const reject = useMutation({ mutationFn: () => api.rejectDraft(item.id), onSuccess: onDone });
  const fields = useMemo(() => new Set(item.draft?.fields ?? []), [item.draft]);
  const isNew = item.status === "draft";
  const correct = item.answer?.choiceIds ?? [];
  const busy = accept.isPending || reject.isPending;
  const ai = (f: string) => isNew || fields.has(f);
  const names = draftFieldNames(item.draft?.fields ?? []);

  return (
    <li className="draft-card">
      <p className="question-meta">
        {item.packName}
        {item.topics?.length ? `. ${item.topics.map((t) => topicNames[t] ?? t).join(", ")}` : ""}
        {item.difficulty ? `. Difficulty ${item.difficulty} of 5` : ""}
      </p>
      <p className="draft-what">
        {isNew ? "New question written by the tutor" : `Tutor wrote: ${names.join(", ")}`}
        {item.draft?.by && <span className="muted"> ({item.draft.by})</span>}
      </p>
      {item.draft?.notes && <p className="draft-doubt">{item.draft.notes}</p>}
      <Markdown className="prompt">{item.prompt}</Markdown>

      {item.choices && (
        <ol className="draft-choices">
          {item.choices.map((c) => {
            const isRight = correct.includes(c.id);
            return (
              <li key={c.id} className={isRight ? "is-right" : ""}>
                <span className="draft-letter" aria-hidden="true">
                  {c.id}
                </span>
                <div>
                  <Markdown>{c.text}</Markdown>
                  {isRight && <p className="draft-key">Correct answer</p>}
                  {!isRight &&
                    (editing ? (
                      <label className="field">
                        <span className="visually-hidden">Why {c.id} is wrong</span>
                        <textarea
                          rows={2}
                          value={editing.rationales[c.id] ?? ""}
                          placeholder={`Why ${c.id} is wrong`}
                          onChange={(e) =>
                            setEditing({ ...editing, rationales: { ...editing.rationales, [c.id]: e.target.value } })
                          }
                        />
                      </label>
                    ) : (
                      item.choiceRationales?.[c.id] && (
                        <Markdown className={`rationale ${ai("choiceRationales") ? "is-ai" : ""}`}>
                          {item.choiceRationales[c.id]}
                        </Markdown>
                      )
                    ))}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {editing ? (
        <div className="draft-edit">
          <label className="field">
            Explanation
            <textarea
              rows={5}
              value={editing.explanation}
              onChange={(e) => setEditing({ ...editing, explanation: e.target.value })}
            />
          </label>
          <fieldset className="field">
            <legend>Links</legend>
            {editing.resources.map((r, i) => (
              <div key={i} className="link-row">
                <input
                  aria-label={`Link ${i + 1} title`}
                  value={r.title}
                  placeholder="Title"
                  onChange={(e) => {
                    const resources = [...editing.resources];
                    resources[i] = { ...r, title: e.target.value };
                    setEditing({ ...editing, resources });
                  }}
                />
                <input
                  aria-label={`Link ${i + 1} address`}
                  value={r.url}
                  placeholder="https://"
                  aria-invalid={!!r.url && !isWebUrl(r.url)}
                  onChange={(e) => {
                    const resources = [...editing.resources];
                    resources[i] = { ...r, url: e.target.value };
                    setEditing({ ...editing, resources });
                  }}
                />
                <button
                  className="btn quiet"
                  type="button"
                  onClick={() => setEditing({ ...editing, resources: editing.resources.filter((_, j) => j !== i) })}
                >
                  Remove<span className="visually-hidden"> link {i + 1}</span>
                </button>
              </div>
            ))}
            <button
              className="btn quiet"
              type="button"
              onClick={() => setEditing({ ...editing, resources: [...editing.resources, { title: "", url: "" }] })}
            >
              Add a link
            </button>
          </fieldset>
          <div className="tool-fields">
            <label>
              Topic
              <select
                value={editing.topics[0] ?? ""}
                onChange={(e) => setEditing({ ...editing, topics: e.target.value ? [e.target.value] : [] })}
              >
                <option value="">No topic</option>
                {exam.topics.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Difficulty
              <select
                value={editing.difficulty ?? ""}
                onChange={(e) => setEditing({ ...editing, difficulty: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">Not set</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      ) : (
        <>
          {item.explanation && (
            <div className={`draft-explanation ${ai("explanation") ? "is-ai" : ""}`}>
              <p className="draft-label">Explanation</p>
              <Markdown>{item.explanation}</Markdown>
            </div>
          )}
          {(item.resources ?? []).length > 0 && (
            <div className={`resources ${ai("resources") ? "is-ai" : ""}`}>
              <p className="resources-title">Links</p>
              <ul>
                {item.resources!.filter((r) => isWebUrl(r.url)).map((r) => (
                  <li key={r.url}>
                    <a href={r.url} target="_blank" rel="noreferrer">
                      {r.title}
                    </a>{" "}
                    <span className="muted url">{new URL(r.url).hostname}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="question-actions">
        {editing ? (
          <>
            <button className="btn quiet" onClick={() => setEditing(null)} disabled={busy}>
              Cancel
            </button>
            <button className="btn primary" onClick={() => accept.mutate(toEdits(editing))} disabled={busy}>
              Save and accept
            </button>
          </>
        ) : (
          <>
            <button className="btn quiet" onClick={() => reject.mutate()} disabled={busy}>
              {isNew ? "Delete question" : "Reject"}
            </button>
            <button className="btn" onClick={() => setEditing(editState(item))} disabled={busy}>
              Edit
            </button>
            <button className="btn primary" onClick={() => accept.mutate(undefined)} disabled={busy}>
              Accept
            </button>
          </>
        )}
      </div>
      {(accept.error || reject.error) && <p className="error">{(accept.error ?? reject.error)!.message}</p>}
    </li>
  );
}
