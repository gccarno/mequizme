import { useEffect, useRef, useState } from "react";
import { formatClock } from "../lib/format";

/** Countdown to a server deadline, corrected for clock skew using the server's time. */
export function Timer({ deadline, serverTime, onExpire }: { deadline: string; serverTime: string; onExpire: () => void }) {
  const skew = useRef(new Date(serverTime).getTime() - Date.now());
  const end = new Date(deadline).getTime();
  const remaining = () => Math.max(0, (end - (Date.now() + skew.current)) / 1000);
  const [left, setLeft] = useState(remaining);
  const fired = useRef(false);

  useEffect(() => {
    const t = setInterval(() => {
      const r = remaining();
      setLeft(r);
      if (r <= 0 && !fired.current) {
        fired.current = true;
        onExpire();
      }
    }, 250);
    return () => clearInterval(t);
  });

  const level = left <= 60 ? "is-critical" : left <= 300 ? "is-low" : "";
  return (
    <div className={`timer ${level}`} role="timer" aria-label={`Time left ${formatClock(left)}`}>
      <span className="timer-value">{formatClock(left)}</span>
      <span className="timer-label">left</span>
    </div>
  );
}
