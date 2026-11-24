import type { AiJob } from "../api";

/** One line describing a background job, in the learner's terms. */
export function jobLine(job: AiJob, topicNames: Record<string, string> = {}): string {
  const active = job.status === "queued" || job.status === "running";
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (job.kind === "generate") {
    const topic = topicNames[job.params.topic ?? ""] ?? job.params.topic ?? "this topic";
    if (active) return `Writing ${plural(job.params.count ?? 0, "question")} on ${topic}…`;
    if (job.status === "interrupted") return `Writing questions on ${topic} stopped when the app restarted.`;
    if (job.changed === 0) return `Couldn't write new questions on ${topic}.`;
    return `Wrote ${plural(job.changed, "new question")} on ${topic}. Review below.`;
  }
  if (job.status === "queued") return `Waiting to fill in ${plural(job.total, "question")}…`;
  if (job.status === "running") return `Filling in ${job.done} of ${job.total} questions…`;
  if (job.status === "cancelled") return `Stopped after ${job.done} of ${job.total}. ${plural(job.changed, "draft")} saved.`;
  if (job.status === "interrupted") return `Stopped when the app restarted, after ${job.done} of ${job.total}. Start again to finish.`;
  if (job.changed === 0) return `Couldn't fill in any of ${plural(job.total, "question")}.`;
  return `Filled in ${plural(job.changed, "question")}. Review below.`;
}
