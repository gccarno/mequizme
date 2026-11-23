import type { AttemptItem } from "../api";
import { Markdown } from "./Markdown";

/** Explanation and follow-up resources for a revealed item. */
export function Feedback({ item, correct }: { item: AttemptItem; correct: boolean | null }) {
  const resources = item.resources ?? [];
  return (
    <section className={`feedback ${correct ? "is-correct" : "is-wrong"}`} aria-live="polite">
      <p className="feedback-verdict">{correct ? "Correct" : "Not quite"}</p>
      {item.explanation ? (
        <Markdown>{item.explanation}</Markdown>
      ) : (
        <p className="muted">No explanation for this question yet.</p>
      )}
      {resources.length > 0 && (
        <div className="resources">
          <p className="resources-title">{correct ? "Read more" : "Review this"}</p>
          <ul>
            {resources.map((r) => (
              <li key={r.url}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
