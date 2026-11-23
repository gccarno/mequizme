import type { ReactNode } from "react";
import type { AttemptItem } from "../api";
import { Markdown } from "./Markdown";
import { DraftNote } from "./Tutor";

export function isWebUrl(url: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

/** Explanation and follow-up resources for a revealed item. */
export function Feedback({
  item,
  correct,
  children,
}: {
  item: AttemptItem;
  correct: boolean | null;
  children?: ReactNode;
}) {
  // Defense in depth: the pack schema already requires http(s), but never render another scheme.
  const resources = (item.resources ?? []).filter((r) => isWebUrl(r.url));
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
      <DraftNote item={item} />
      {children}
    </section>
  );
}
