import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { HostMaintenancePanel } from "../components/HostMaintenancePanel";
import { operatorFetch, type HostStatus } from "../api/operator";

vi.mock("../api/operator", () => ({ operatorFetch: vi.fn() }));
const connection = { baseUrl: "", token: "operator" };
const status: HostStatus = {
  readiness: { status: "ok", checks: { generation_queue: "ok" } },
  checked_at: Date.now() / 1000, services: { canary: "active", docker: "active" },
  containers: [], uptime_seconds: 7200, load: [0.1, 0.2, 0.3],
  disk_free_bytes: 1024 ** 3 * 10, disk_total_bytes: 1024 ** 3 * 40,
  reboot_required: true, reboot_packages: ["linux-image"], maintenance_hold: false,
  plan: { digest: "b".repeat(64), checked_at: Date.now() / 1000, packages: ["Inst openssl [old] (new)"] }, operation: null,
};
beforeEach(() => { vi.mocked(operatorFetch).mockReset().mockResolvedValue(status); });

it("shows a real update preview and requires confirmation before applying", async () => {
  const user = userEvent.setup();
  render(<HostMaintenancePanel connection={connection} />);
  expect(await screen.findByText("Host reboot required")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Review package update" }));
  expect(operatorFetch).toHaveBeenCalledTimes(1);
  vi.mocked(operatorFetch).mockResolvedValueOnce({ action: "update", phase: "queued", request_id: "id", updated_at: Date.now() / 1000 });
  await user.click(screen.getByRole("button", { name: "Apply updates" }));
  const options = vi.mocked(operatorFetch).mock.calls[1][2];
  expect(JSON.parse(options?.body as string)).toMatchObject({ action: "update", plan_digest: "b".repeat(64) });
  expect((screen.getByRole("button", { name: "Check for updates" }) as HTMLButtonElement).disabled).toBe(true);
});

it("disables mutations on existing maintenance holds", async () => {
  vi.mocked(operatorFetch).mockResolvedValue({ ...status, maintenance_hold: true });
  render(<HostMaintenancePanel connection={connection} />);
  await screen.findByText("Active — deployment is blocked");
  expect((screen.getByRole("button", { name: "Review host reboot" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Review package update" }) as HTMLButtonElement).disabled).toBe(true);
});

it("keeps the last status and explains lost contact without retrying a mutation", async () => {
  const user = userEvent.setup();
  render(<HostMaintenancePanel connection={connection} />);
  await screen.findByText("Host reboot required");
  await user.click(screen.getByRole("button", { name: "Review host reboot" }));
  vi.mocked(operatorFetch).mockRejectedValueOnce(new Error("Network unavailable"));
  await user.click(screen.getByRole("button", { name: "Reboot host" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("outcome may be unknown"));
  expect(operatorFetch).toHaveBeenCalledTimes(2);
  expect(screen.getByText("Host reboot required")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Review host reboot" }) as HTMLButtonElement).disabled).toBe(true);
});

it("makes an uninstalled agent visible without invented host data", async () => {
  vi.mocked(operatorFetch).mockRejectedValue(new Error("Host agent unavailable"));
  render(<HostMaintenancePanel connection={connection} />);
  expect((await screen.findByRole("alert")).textContent).toContain("Host agent unavailable");
  expect(screen.queryByText("Host reboot required")).toBeNull();
});
