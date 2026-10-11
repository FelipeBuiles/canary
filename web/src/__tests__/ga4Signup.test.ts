import { beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ ready: false, claim: vi.fn(), track: vi.fn() }));
vi.mock("../lib/ga4", () => ({ ga4Ready: () => mocks.ready, trackGa4Signup: mocks.track }));
vi.mock("../api/events", () => ({ claimGa4Signup: mocks.claim }));
beforeEach(() => { vi.resetModules(); mocks.ready = false; mocks.claim.mockReset(); mocks.track.mockReset(); });

it("waits for consent and Google readiness, then preserves a single claim across React remounts", async () => {
  const { setGa4SignupAccount, reportGa4Signup } = await import("../lib/ga4Signup");
  setGa4SignupAccount("author");
  await reportGa4Signup("author");
  expect(mocks.claim).not.toHaveBeenCalled();
  mocks.ready = true;
  let resolve!: (value: boolean) => void;
  mocks.claim.mockReturnValue(new Promise<boolean>(done => { resolve = done; }));
  const firstEffect = reportGa4Signup("author");
  setGa4SignupAccount("author");
  await reportGa4Signup("author");
  resolve(true);
  await firstEffect;
  await reportGa4Signup("author");
  expect(mocks.claim).toHaveBeenCalledOnce();
  expect(mocks.track).toHaveBeenCalledOnce();
});

it.each(["account", "consent"])("suppresses a claim response after the %s changes", async change => {
  const { setGa4SignupAccount, reportGa4Signup } = await import("../lib/ga4Signup");
  mocks.ready = true;
  setGa4SignupAccount("author");
  let resolve!: (value: boolean) => void;
  mocks.claim.mockReturnValue(new Promise<boolean>(done => { resolve = done; }));
  const pending = reportGa4Signup("author");
  if (change === "account") setGa4SignupAccount(undefined);
  else mocks.ready = false;
  resolve(true);
  await pending;
  expect(mocks.track).not.toHaveBeenCalled();
});

it("does not turn a returning account or a failed claim into a conversion", async () => {
  const { setGa4SignupAccount, reportGa4Signup } = await import("../lib/ga4Signup");
  mocks.ready = true;
  mocks.claim.mockResolvedValue(false);
  setGa4SignupAccount("returning-author");
  await reportGa4Signup("returning-author");
  expect(mocks.track).not.toHaveBeenCalled();
});
