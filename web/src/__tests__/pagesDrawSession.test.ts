import { describe, expect, it } from "vitest";
import type { GenerationJob } from "../types/api";
import {
  initialPagesDrawSession, isDrawStarting, pageActionErrorFor, pageDrawInput, pagesDrawReducer as reduce,
  type PagesDrawEvent, type PagesDrawSession,
} from "../lib/pagesDrawSession";

const job = (id: string, status: string) => ({ id, status }) as unknown as GenerationJob;
const run = (events: PagesDrawEvent[], from: PagesDrawSession = initialPagesDrawSession) => events.reduce(reduce, from);

describe("pages draw session", () => {
  it("tracks a draw from request to accepted job", () => {
    const requested = run([{ type: "draw_requested", pageNumber: 2 }]);
    expect(isDrawStarting(requested, 2)).toBe(true);
    const accepted = reduce(requested, { type: "draw_accepted", pageNumber: 2, jobId: "j1" });
    expect(isDrawStarting(accepted, 2)).toBe(false);
    expect(pageDrawInput(accepted, 2).submitted).toBe(true);
    expect(pageDrawInput(accepted, 3).submitted).toBe(false);
  });

  it("clears the previous failure and error when a draw is requested", () => {
    const failed = run([
      { type: "jobs_accepted", jobs: [{ jobId: "j1", pageNumber: 1 }] },
      { type: "jobs_settled", settled: [{ jobId: "j1", pageNumber: 1, job: job("j1", "failed") }] },
      { type: "analysis_rejected", pageNumber: 1, error: new Error("x") },
    ]);
    expect(pageDrawInput(failed, 1).failure?.id).toBe("j1");
    const again = reduce(failed, { type: "draw_requested", pageNumber: 1 });
    expect(pageDrawInput(again, 1).failure).toBeUndefined();
    expect(pageActionErrorFor(again, 1)).toBeUndefined();
  });

  it("keeps the error and stops starting when a draw is rejected", () => {
    const error = new Error("nope");
    const state = run([{ type: "draw_requested", pageNumber: 4 }, { type: "draw_rejected", pageNumber: 4, error }]);
    expect(isDrawStarting(state, 4)).toBe(false);
    expect(pageActionErrorFor(state, 4)).toBe(error);
  });

  it("replaces the batch on each start and clears it on rejection", () => {
    const first = run([{ type: "batch_started", pageNumbers: [1, 2] }]);
    expect([1, 2, 3].map(n => pageDrawInput(first, n).batch)).toEqual([true, true, false]);
    const second = reduce(first, { type: "batch_started", pageNumbers: [3] });
    expect([1, 2, 3].map(n => pageDrawInput(second, n).batch)).toEqual([false, false, true]);
    const cleared = reduce(second, { type: "batch_rejected" });
    expect(pageDrawInput(cleared, 3).batch).toBe(false);
  });

  it("settles jobs: drops the job, the batch flag, and records only failures", () => {
    const state = run([
      { type: "batch_started", pageNumbers: [1, 2] },
      { type: "jobs_accepted", jobs: [{ jobId: "a", pageNumber: 1 }, { jobId: "b", pageNumber: 2 }, { jobId: "c", pageNumber: 3 }] },
      { type: "jobs_settled", settled: [
        { jobId: "a", pageNumber: 1, job: job("a", "failed") },
        { jobId: "b", pageNumber: 2, job: job("b", "succeeded") },
      ] },
    ]);
    expect(pageDrawInput(state, 1)).toMatchObject({ batch: false, submitted: false, failure: { id: "a" } });
    expect(pageDrawInput(state, 2)).toMatchObject({ batch: false, submitted: false, failure: undefined });
    expect(pageDrawInput(state, 3).submitted).toBe(true);
  });

  it("a later success clears an earlier failure", () => {
    const state = run([
      { type: "jobs_settled", settled: [{ jobId: "a", pageNumber: 1, job: job("a", "failed") }] },
      { type: "jobs_settled", settled: [{ jobId: "b", pageNumber: 1, job: job("b", "succeeded") }] },
    ]);
    expect(pageDrawInput(state, 1).failure).toBeUndefined();
  });

  it("a job accepted from review clears the page failure", () => {
    const state = run([
      { type: "jobs_settled", settled: [{ jobId: "a", pageNumber: 5, job: job("a", "failed") }] },
      { type: "job_accepted_for_review", jobId: "r", pageNumber: 5 },
    ]);
    expect(pageDrawInput(state, 5)).toMatchObject({ failure: undefined, submitted: true });
  });

  it("successful analysis clears failure and action error", () => {
    const state = run([
      { type: "jobs_settled", settled: [{ jobId: "a", pageNumber: 1, job: job("a", "failed") }] },
      { type: "analysis_rejected", pageNumber: 1, error: new Error("x") },
      { type: "analysis_succeeded", pageNumber: 1 },
    ]);
    expect(pageDrawInput(state, 1).failure).toBeUndefined();
    expect(pageActionErrorFor(state, 1)).toBeUndefined();
  });
});
