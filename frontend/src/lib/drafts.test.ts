import { describe, expect, it } from "vitest";
import type { AiJob } from "../api";
import { jobLine } from "./drafts";

const job = (over: Partial<AiJob>): AiJob => ({
  id: "j",
  kind: "enrich",
  params: {},
  status: "running",
  total: 60,
  done: 12,
  changed: 12,
  errors: [],
  createdAt: "",
  finishedAt: null,
  ...over,
});

describe("jobLine", () => {
  it("describes fill-in progress and results", () => {
    expect(jobLine(job({}))).toBe("Filling in 12 of 60 questions…");
    expect(jobLine(job({ status: "done", changed: 1 }))).toBe("Filled in 1 question. Review below.");
    expect(jobLine(job({ status: "cancelled", done: 20, changed: 19 }))).toBe("Stopped after 20 of 60. 19 drafts saved.");
  });
  it("names the topic for new questions", () => {
    const g = job({ kind: "generate", params: { topic: "t", count: 5 } });
    expect(jobLine(g, { t: "Model Deployment" })).toBe("Writing 5 questions on Model Deployment…");
    expect(jobLine({ ...g, status: "done", changed: 4 }, { t: "Model Deployment" })).toBe(
      "Wrote 4 new questions on Model Deployment. Review below.",
    );
    expect(jobLine({ ...g, status: "failed", changed: 0 })).toBe("Couldn't write new questions on t.");
  });
});
