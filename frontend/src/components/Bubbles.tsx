import type { Choice } from "../types/studypack";
import { Markdown } from "./Markdown";

export type BubbleMark = "correct" | "missed" | "wrong" | undefined;

interface Props {
  choices: Choice[];
  selected: string[];
  multi: boolean;
  disabled?: boolean;
  /** After reveal: mark each choice correct / wrong pick / missed correct one. */
  marks?: Record<string, BubbleMark>;
  rationales?: Record<string, string> | null;
  onToggle?: (choiceId: string) => void;
  name: string;
}

/**
 * Answer choices drawn as an answer sheet: each letter is a bubble that fills like a pencil mark.
 * Uses real radio/checkbox inputs so keyboard and screen readers work natively.
 */
export function Bubbles({ choices, selected, multi, disabled, marks, rationales, onToggle, name }: Props) {
  return (
    <fieldset className="bubbles" disabled={disabled}>
      <legend className="visually-hidden">Answer choices</legend>
      {choices.map((c) => {
        const checked = selected.includes(c.id);
        const mark = marks?.[c.id];
        return (
          <label key={c.id} className={`bubble-row ${checked ? "is-picked" : ""} ${mark ? `is-${mark}` : ""}`}>
            <input
              type={multi ? "checkbox" : "radio"}
              name={name}
              value={c.id}
              checked={checked}
              onChange={() => onToggle?.(c.id)}
            />
            <span className="bubble" aria-hidden="true">
              {c.id}
            </span>
            <span className="bubble-text">
              <Markdown>{c.text}</Markdown>
              {mark && (
                <span className="bubble-verdict">
                  {mark === "correct" && (checked ? "Your answer, correct" : "Correct answer")}
                  {mark === "wrong" && "Your answer"}
                  {mark === "missed" && "Correct answer, not picked"}
                </span>
              )}
              {mark && rationales?.[c.id] && <Markdown className="rationale">{rationales[c.id]}</Markdown>}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

export function marksFor(choices: Choice[], picked: string[], correct: string[]): Record<string, BubbleMark> {
  const out: Record<string, BubbleMark> = {};
  for (const c of choices) {
    const isCorrect = correct.includes(c.id);
    const isPicked = picked.includes(c.id);
    if (isCorrect) out[c.id] = isPicked || correct.length === 1 ? "correct" : "missed";
    else if (isPicked) out[c.id] = "wrong";
  }
  return out;
}
