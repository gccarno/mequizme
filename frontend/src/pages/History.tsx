import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDate, percent } from "../lib/format";

export function History() {
  const attempts = useQuery({ queryKey: ["attempts"], queryFn: api.attempts });
  if (attempts.isPending) return <p className="page muted">Loading history…</p>;
  if (attempts.error) return <p className="page error">{attempts.error.message}</p>;
  if (!attempts.data.length)
    return (
      <div className="page empty">
        <h1>No quizzes taken yet</h1>
        <p>
          Pick a pack in the <Link to="/">library</Link> and start a practice or timed quiz.
        </p>
      </div>
    );

  return (
    <div className="page history">
      <h1>History</h1>
      <table>
        <thead>
          <tr>
            <th scope="col">Quiz</th>
            <th scope="col">Mode</th>
            <th scope="col">Started</th>
            <th scope="col" className="num">
              Score
            </th>
          </tr>
        </thead>
        <tbody>
          {attempts.data.map((a) => (
            <tr key={a.id}>
              <td>
                <Link to={a.submittedAt ? `/attempt/${a.id}/review` : `/attempt/${a.id}`}>{a.name}</Link>
              </td>
              <td>{a.mode === "exam" ? "Timed" : "Practice"}</td>
              <td>{formatDate(a.startedAt)}</td>
              <td className="num">
                {a.submittedAt ? `${a.score}/${a.total} (${percent(a.score ?? 0, a.total)}%)` : "In progress"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
