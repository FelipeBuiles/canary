import type { GenerationJob } from "../types/api";

export interface PageDraw {
  starting: boolean;
  batch: boolean;
  failure?: GenerationJob;
  actionError?: Error;
}

export interface PagesDrawSession {
  /** Page each accepted-but-unsettled job was submitted for, by job id. */
  jobs: Record<string, number>;
  pages: Record<number, PageDraw>;
}

export interface SettledJob {
  jobId: string;
  pageNumber: number;
  job: GenerationJob;
}

export type PagesDrawEvent =
  | { type: "draw_requested"; pageNumber: number }
  | { type: "draw_accepted"; pageNumber: number; jobId: string }
  | { type: "draw_rejected"; pageNumber: number; error: Error }
  | { type: "jobs_accepted"; jobs: { jobId: string; pageNumber: number }[] }
  | { type: "job_accepted_for_review"; jobId: string; pageNumber: number }
  | { type: "batch_started"; pageNumbers: number[] }
  | { type: "batch_rejected" }
  | { type: "analysis_succeeded"; pageNumber: number }
  | { type: "analysis_rejected"; pageNumber: number; error: Error }
  | { type: "jobs_settled"; settled: SettledJob[] };

export const initialPagesDrawSession: PagesDrawSession = { jobs: {}, pages: {} };

const IDLE: PageDraw = { starting: false, batch: false };

function patchPage(state: PagesDrawSession, pageNumber: number, patch: Partial<PageDraw>): PagesDrawSession {
  const next = { ...(state.pages[pageNumber] ?? IDLE), ...patch };
  return { ...state, pages: { ...state.pages, [pageNumber]: next } };
}

function withoutFailure(state: PagesDrawSession, pageNumber: number): PagesDrawSession {
  return state.pages[pageNumber]?.failure ? patchPage(state, pageNumber, { failure: undefined }) : state;
}

function addJobs(state: PagesDrawSession, jobs: { jobId: string; pageNumber: number }[]): PagesDrawSession {
  return { ...state, jobs: { ...state.jobs, ...Object.fromEntries(jobs.map(({ jobId, pageNumber }) => [jobId, pageNumber])) } };
}

export function pagesDrawReducer(state: PagesDrawSession, event: PagesDrawEvent): PagesDrawSession {
  switch (event.type) {
    case "draw_requested":
      return patchPage(state, event.pageNumber, { starting: true, actionError: undefined, failure: undefined });
    case "draw_accepted":
      return addJobs(patchPage(state, event.pageNumber, { starting: false }), [event]);
    case "draw_rejected":
      return patchPage(state, event.pageNumber, { starting: false, actionError: event.error });
    case "jobs_accepted":
      return addJobs(state, event.jobs);
    case "job_accepted_for_review":
      return addJobs(withoutFailure(state, event.pageNumber), [event]);
    case "batch_started":
    case "batch_rejected": {
      const queued = event.type === "batch_started" ? new Set(event.pageNumbers) : new Set<number>();
      const pages: Record<number, PageDraw> = {};
      for (const [key, draw] of Object.entries(state.pages)) pages[Number(key)] = { ...draw, batch: false };
      for (const pageNumber of queued) pages[pageNumber] = { ...(pages[pageNumber] ?? IDLE), batch: true };
      return { ...state, pages };
    }
    case "analysis_succeeded":
      return patchPage(state, event.pageNumber, { failure: undefined, actionError: undefined });
    case "analysis_rejected":
      return patchPage(state, event.pageNumber, { actionError: event.error });
    case "jobs_settled": {
      let next = state;
      for (const pageNumber of new Set(event.settled.map(entry => entry.pageNumber))) {
        next = patchPage(next, pageNumber, { batch: false });
      }
      for (const { pageNumber, job } of event.settled) {
        next = patchPage(next, pageNumber, { failure: job.status === "failed" ? job : undefined });
      }
      const jobs = { ...next.jobs };
      for (const { jobId } of event.settled) delete jobs[jobId];
      return { ...next, jobs };
    }
  }
}

export function pageDrawInput(state: PagesDrawSession, pageNumber: number) {
  const draw = state.pages[pageNumber];
  return {
    starting: !!draw?.starting,
    batch: !!draw?.batch,
    submitted: Object.values(state.jobs).includes(pageNumber),
    failure: draw?.failure,
  };
}

export function pageActionErrorFor(state: PagesDrawSession, pageNumber: number) {
  return state.pages[pageNumber]?.actionError;
}

export function isDrawStarting(state: PagesDrawSession, pageNumber: number) {
  return !!state.pages[pageNumber]?.starting;
}
