import type { Confidence as Level } from "../api";

export const CONFIDENCE_LABELS: Record<Level, string> = { 1: "Guessing", 2: "Unsure", 3: "Sure" };
export const CONFIDENCE_KEYS: Record<string, Level> = { G: 1, U: 2, S: 3 };

/** "How sure are you?" Optional; lucky guesses earn half credit and sure-but-wrong answers get called out. */
export function ConfidencePicker({
  value,
  onChange,
  disabled,
}: {
  value: Level | null;
  onChange: (v: Level) => void;
  disabled?: boolean;
}) {
  if (disabled) {
    return value ? <p className="confidence-note muted">You were {CONFIDENCE_LABELS[value].toLowerCase()}.</p> : null;
  }
  return (
    <div className="confidence" role="radiogroup" aria-label="How sure are you?">
      <span className="confidence-label">How sure are you?</span>
      {([1, 2, 3] as Level[]).map((c) => (
        <button
          key={c}
          type="button"
          role="radio"
          aria-checked={value === c}
          className={`confidence-opt ${value === c ? "is-on" : ""}`}
          onClick={() => onChange(c)}
        >
          {CONFIDENCE_LABELS[c]}
        </button>
      ))}
    </div>
  );
}
