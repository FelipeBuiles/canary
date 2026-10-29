import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { EnvironmentPanel } from "../components/EnvironmentPanel";
import { ConfigError, configRequest, type ConfigPlan, type ConfigStatus } from "../api/configuration";

vi.mock("../api/configuration", async importOriginal => ({ ...await importOriginal<typeof import("../api/configuration")>(), configRequest: vi.fn(), uploadBundle: vi.fn() }));
const connection = { baseUrl: "", token: "operator" };
let state: ConfigStatus;
let preview: ConfigPlan;
let events: Array<{ seq: number; phase: string; kind: string; at: number }>;
beforeEach(() => {
  sessionStorage.clear();
  events = [];
  preview = { plan_id: "", digest: "d".repeat(64), baseline: "revision", image: "image@digest", bundle_sha256: "bundle", changes: { CANARY_RUNWARE_FIRST_ENABLED: { before: "false", after: "true" } }, secret_changes: { RUNWARE_API_KEY: "changed" }, checks: { RUNWARE_API_KEY: "present" }, activity: {}, restart_required: true, plan_expires_at: Date.now() / 1000 + 1800, authorization_expires_at: null, effective_expires_at: Date.now() / 1000 + 1800, recovery_verification: null };
  state = { checked_at: Date.now() / 1000, revision: "revision", image: "image@digest", bundle_sha256: "bundle", loader_sha256: "loader", observation: { match: "match", observed_at: Date.now() / 1000, stale: false }, values: { CANARY_RUNWARE_FIRST_ENABLED: "false" }, schema: { CANARY_RUNWARE_FIRST_ENABLED: { type: "boolean", backoffice: "editable", description: "Changes which provider gets paid." } }, secret_names: ["RUNWARE_API_KEY"], operation: null, maintenance_hold: false };
  vi.mocked(configRequest).mockReset().mockImplementation(async (_connection, path, body) => {
    if (path.startsWith("status")) return state;
    if (path.startsWith("events")) return { events: events.filter(event => event.seq > Number(path.split("after=")[1])), after: events.at(-1)?.seq ?? 0 };
    if (path === "plan") {
      const request = body as { request_id: string };
      preview.plan_id = request.request_id;
      state = { ...state, operation: { request_id: request.request_id, phase: "plan_ready", plan: preview, receipt: null } };
      return { ...state.operation, phase: "accepted" };
    }
    return {};
  });
});
async function ready() {
  const user = userEvent.setup();
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Current deployment");
  await user.selectOptions(screen.getByLabelText("CANARY_RUNWARE_FIRST_ENABLED"), "true");
  await user.click(screen.getByRole("button", { name: "Preview changes" }));
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await screen.findByText("Review plan");
  return user;
}
it("shows public and secret diffs and requires approval of the specific digest", async () => {
  const user = await ready();
  expect(screen.getByText("CANARY_RUNWARE_FIRST_ENABLED: false → true")).toBeTruthy();
  expect(screen.getByText("RUNWARE_API_KEY: changed")).toBeTruthy();
  expect(configRequest).not.toHaveBeenCalledWith(connection, "apply", expect.anything());
  await user.click(screen.getByRole("button", { name: "Review apply" }));
  expect(screen.getByText(/Drain deadline: 30 minutes/)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Apply this plan" }));
  expect(configRequest).toHaveBeenCalledWith(connection, "apply", expect.objectContaining({ plan_id: preview.plan_id, plan_digest: preview.digest }));
});
it("disables apply for a changed baseline and an expired authorization", async () => {
  preview.authorization_expires_at = Date.now() / 1000 - 1;
  preview.effective_expires_at = preview.authorization_expires_at;
  state.revision = "changed";
  await ready();
  expect(screen.getByText("authorization_expired")).toBeTruthy();
  expect(screen.getByText(/baseline_changed/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Review apply" }) as HTMLButtonElement).disabled).toBe(true);
});
it("blocks mutations on stale observations", async () => {
  state.observation.stale = true;
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Current deployment");
  expect((screen.getByRole("button", { name: "Preview changes" }) as HTMLButtonElement).disabled).toBe(true);
});
it("retains intent as unconfirmed and fills the event gap on reconnect", async () => {
  const user = await ready();
  events = [{ seq: 1, phase: "starting", kind: "intent", at: Date.now() / 1000 }];
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await screen.findByText(/starting · unconfirmed/);
  vi.mocked(configRequest).mockRejectedValueOnce(new Error("connection lost"));
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  expect(await screen.findByText(/Current host state is unknown/)).toBeTruthy();
  events.push({ seq: 2, phase: "starting", kind: "result", at: Date.now() / 1000 });
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await waitFor(() => expect(screen.queryByText(/starting · unconfirmed/)).toBeNull());
  expect(configRequest).toHaveBeenCalledWith(connection, expect.stringContaining("after=1"));
});
it.each(["rejected_busy", "invalid_request", "host_agent_unavailable", "http_403"])("recovers a preview rejected with %s before operation creation", async code => {
  const user = userEvent.setup();
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Current deployment");
  await user.selectOptions(screen.getByLabelText("CANARY_RUNWARE_FIRST_ENABLED"), "true");
  vi.mocked(configRequest).mockRejectedValueOnce(new ConfigError(code));
  await user.click(screen.getByRole("button", { name: "Preview changes" }));
  await screen.findByText(code);
  expect(sessionStorage.getItem("canary-config-operation:")).toBe("");
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Preview changes" }).matches(":disabled")).toBe(false));
  expect(configRequest).toHaveBeenLastCalledWith(connection, "status");
  await user.click(screen.getByRole("button", { name: "Preview changes" }));
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await screen.findByText("Review plan");
});
it.each(["request_outcome_unknown", "configuration_failed", "http_503"])("retains a preview UUID after an uncertain %s response", async code => {
  const user = userEvent.setup();
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Current deployment");
  vi.mocked(configRequest).mockRejectedValueOnce(new ConfigError(code));
  await user.click(screen.getByRole("button", { name: "Preview changes" }));
  await screen.findByText(code);
  const call = vi.mocked(configRequest).mock.calls.find(([, path]) => path === "plan")!;
  const id = (call[2] as { request_id: string }).request_id;
  expect(sessionStorage.getItem("canary-config-operation:")).toBe(id);
  expect(screen.getByRole("button", { name: "Preview changes" }).matches(":disabled")).toBe(true);
  expect(vi.mocked(configRequest).mock.calls.filter(([, path]) => path === "plan")).toHaveLength(1);
});
it("observes the original apply UUID after a lost reply without resubmission", async () => {
  const user = await ready();
  await user.click(screen.getByRole("button", { name: "Review apply" }));
  vi.mocked(configRequest).mockRejectedValueOnce(new ConfigError("request_outcome_unknown"));
  await user.click(screen.getByRole("button", { name: "Apply this plan" }));
  await screen.findByText("request_outcome_unknown");
  const call = vi.mocked(configRequest).mock.calls.find(([, path]) => path === "apply")!;
  const id = (call[2] as { request_id: string }).request_id;
  expect(sessionStorage.getItem("canary-config-operation:")).toBe(id);
  state.operation = { request_id: id, phase: "complete", plan: null, receipt: { admission_open: true } };
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await screen.findByText("Receipt");
  expect(vi.mocked(configRequest).mock.calls.filter(([, path]) => path === "apply")).toHaveLength(1);
  expect(configRequest).toHaveBeenCalledWith(connection, `status?operation=${id}`);
});

it("loads a locally prepared proposal and applies its exact digest after review", async () => {
  preview.plan_id = "local-proposal";
  state.operation = { request_id: preview.plan_id, phase: "plan_ready", plan: preview, receipt: null };
  const user = userEvent.setup();
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Prepared — awaiting apply");
  expect(screen.getByText(/These values are staged/)).toBeTruthy();
  expect(configRequest).not.toHaveBeenCalledWith(connection, "apply", expect.anything());
  await user.click(screen.getByRole("button", { name: "Review apply" }));
  await user.click(screen.getByRole("button", { name: "Apply this plan" }));
  expect(configRequest).toHaveBeenCalledWith(connection, "apply", expect.objectContaining({ plan_id: "local-proposal", plan_digest: preview.digest }));
});

it.each(["setting", "ops-token"])("keeps imported %s changes restricted to SSH", async kind => {
  if (kind === "setting") state.schema.CANARY_RUNWARE_FIRST_ENABLED.backoffice = "ssh_only";
  else preview.secret_changes.CANARY_OPS_TOKEN = "changed";
  state.operation = { request_id: "local-proposal", phase: "plan_ready", plan: preview, receipt: null };
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText(/This proposal includes changes restricted to operator SSH/);
  expect(screen.getByRole("button", { name: "Review apply" }).matches(":disabled")).toBe(true);
});

it("loads the latest local proposal when an older operation is pinned", async () => {
  sessionStorage.setItem("canary-config-operation:", "old-operation");
  const old = { request_id: "old-operation", phase: "complete", plan: null, receipt: { after_revision: "revision" } };
  state.operation = { request_id: "new-proposal", phase: "plan_ready", plan: preview, receipt: null };
  const handler = vi.mocked(configRequest).getMockImplementation()!;
  vi.mocked(configRequest).mockImplementation(async (connection, path, body) => path === "status?operation=old-operation" ? { ...state, operation: old } : handler(connection, path, body));
  const user = userEvent.setup();
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Applied and verified");
  await user.click(screen.getByRole("button", { name: "Load latest proposal" }));
  await screen.findByText("Prepared — awaiting apply");
  expect(sessionStorage.getItem("canary-config-operation:")).toBe("new-proposal");
});

it("does not call a completed receipt verified until the running revision matches", async () => {
  state.operation = { request_id: "apply", phase: "complete", plan: null, receipt: { after_revision: "new-revision" } };
  const user = userEvent.setup();
  render(<EnvironmentPanel connection={connection} />);
  await screen.findByText("Applied — checking running configuration");
  state.revision = "new-revision";
  await user.click(screen.getByRole("button", { name: "Refresh environment" }));
  await screen.findByText("Applied and verified");
  expect(screen.queryByRole("button", { name: "Review apply" })).toBeNull();
});
