import { useEffect, useRef, useState } from "react";
import type { TrendPoint } from "../api";
import { formatDate, formatDay } from "../lib/format";

const pct = (p: TrendPoint) => (p.total ? p.correct / p.total : 0);
const tip = (p: TrendPoint) =>
  `${p.name}: ${p.correct} of ${p.total} (${Math.round(pct(p) * 100)}%), ${formatDate(p.at)}`;

/**
 * Printed score-report scale: 0–100 with the passing line marked and your estimate as a pointer.
 * The numbers are in the text beside it, so the scale is decorative for screen readers.
 */
export function ScoreScale({
  score,
  passing,
  tone,
}: {
  score: number;
  passing: number;
  tone: string;
}) {
  return (
    <div className={`scale tone-${tone}`} aria-hidden="true">
      <div className="scale-track">
        <span className="scale-fill" style={{ width: `${score * 100}%` }} />
        <span className="scale-pass" style={{ left: `${passing * 100}%` }}>
          <span>pass {Math.round(passing * 100)}</span>
        </span>
      </div>
      <div className="scale-ticks">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
    </div>
  );
}

/** Mastery bar with the passing line as a tick. */
export function MasteryBar({
  value,
  passing,
}: {
  value: number;
  passing: number;
}) {
  return (
    <span className="mastery-bar" aria-hidden="true">
      <span
        className={`mastery-fill ${value >= passing ? "is-pass" : ""}`}
        style={{ width: `${value * 100}%` }}
      />
      <span className="mastery-pass" style={{ left: `${passing * 100}%` }} />
    </span>
  );
}

/** Tiny per-topic trend: one dot per quiz, newest on the right. Hover a dot for the detail. */
export function Sparkline({
  points,
  passing,
}: {
  points: TrendPoint[];
  passing: number;
}) {
  if (points.length === 0)
    return <span className="muted spark-empty">No quizzes yet</span>;
  const w = 96,
    h = 26,
    pad = 4;
  const x = (i: number) =>
    points.length === 1
      ? w / 2
      : pad + (i * (w - 2 * pad)) / (points.length - 1);
  const y = (v: number) => h - pad - v * (h - 2 * pad);
  return (
    <svg
      className="spark"
      viewBox={`0 0 ${w} ${h}`}
      width={w}
      height={h}
      role="img"
      aria-label={`Last ${points.length} quiz${points.length === 1 ? "" : "zes"}: ${points.map((p) => `${Math.round(pct(p) * 100)}%`).join(", ")}`}
    >
      <line
        className="spark-pass"
        x1={0}
        x2={w}
        y1={y(passing)}
        y2={y(passing)}
      />
      {points.length > 1 && (
        <polyline
          className="spark-line"
          points={points.map((p, i) => `${x(i)},${y(pct(p))}`).join(" ")}
        />
      )}
      {points.map((p, i) => (
        <circle
          key={p.attemptId}
          className="spark-dot"
          cx={x(i)}
          cy={y(pct(p))}
          r={2.5}
        >
          <title>{tip(p)}</title>
        </circle>
      ))}
    </svg>
  );
}

/** Score per quiz over time, with the passing line. */
export function TrendChart({
  points,
  passing,
}: {
  points: TrendPoint[];
  passing: number;
}) {
  // Draw at the container's real width so labels stay at their true size on a phone.
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) =>
      setW(Math.max(240, Math.min(704, Math.round(e.contentRect.width)))),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const h = 180,
    left = 34,
    right = 12,
    top = 10,
    bottom = 22;
  const x = (i: number) =>
    points.length === 1
      ? (left + w - right) / 2
      : left + (i * (w - left - right)) / (points.length - 1);
  const y = (v: number) => top + (1 - v) * (h - top - bottom);
  return (
    <div ref={box} className="trend-box">
      <svg
        className="trend"
        viewBox={`0 0 ${w} ${h}`}
        width={w}
        height={h}
        role="img"
        aria-label={`Scores for your last ${points.length} quizzes, oldest first: ${points.map((p) => `${Math.round(pct(p) * 100)}%`).join(", ")}`}
      >
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line
              className="trend-grid"
              x1={left}
              x2={w - right}
              y1={y(v)}
              y2={y(v)}
            />
            <text
              className="trend-axis"
              x={left - 6}
              y={y(v) + 4}
              textAnchor="end"
            >
              {v * 100}
            </text>
          </g>
        ))}
        <line
          className="trend-pass"
          x1={left}
          x2={w - right}
          y1={y(passing)}
          y2={y(passing)}
        />
        <text
          className="trend-axis"
          x={w - right}
          y={y(passing) - 5}
          textAnchor="end"
        >
          pass
        </text>
        {points.length > 1 && (
          <polyline
            className="trend-line"
            points={points.map((p, i) => `${x(i)},${y(pct(p))}`).join(" ")}
          />
        )}
        {points.map((p, i) => (
          <g key={p.attemptId} className="trend-point">
            {/* larger invisible hit target than the mark */}
            <circle cx={x(i)} cy={y(pct(p))} r={12} className="trend-hit">
              <title>{tip(p)}</title>
            </circle>
            <circle
              cx={x(i)}
              cy={y(pct(p))}
              r={4}
              className={`trend-dot ${p.mode === "exam" ? "is-exam" : ""}`}
            />
          </g>
        ))}
        <text className="trend-axis" x={left} y={h - 4}>
          {formatDay(points[0].at)}
        </text>
        {points.length > 1 && (
          <text className="trend-axis" x={w - right} y={h - 4} textAnchor="end">
            {formatDay(points.at(-1)!.at)}
          </text>
        )}
      </svg>
    </div>
  );
}
