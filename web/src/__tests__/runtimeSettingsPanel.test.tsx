import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RuntimeSettingsPanel } from "../components/RuntimeSettingsPanel";

const connection = { baseUrl: "https://ops.example.test", token: "operator-secret" };
const setting = (overrides: Record<string, unknown>) => ({
  key: "CANARY_CARD_GRANT_CREDITS", kind: "int", description: "Credits granted for a verified card.", minimum: 0, maximum: 10000,
  unset_means: "off", editable: true, value: "", source: "unset", environment_value: "", ...overrides,
});
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const fetchMock = vi.fn();

beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

describe("Live settings panel", () => {
  it("saves a value, shows where it comes from, and removes it", async () => {
    fetchMock
      .mockImplementationOnce(() => reply({ store: "loaded", settings: [setting({}), setting({ key: "CANARY_SPONSORED_GRANT_ROUTES_ONLY", kind: "bool", editable: false, minimum: null, maximum: null })] }))
      .mockImplementationOnce(() => reply({ store: "loaded", settings: [setting({ value: "1200", source: "database" })] }))
      .mockImplementationOnce(() => reply({ store: "loaded", settings: [setting({})] }));
    render(<RuntimeSettingsPanel connection={connection} />);

    const input = await screen.findByLabelText("New value for CANARY_CARD_GRANT_CREDITS");
    expect(screen.getAllByText(/Not set: off/)).toHaveLength(2);
    expect(screen.queryByLabelText("New value for CANARY_SPONSORED_GRANT_ROUTES_ONLY")).toBeNull();
    fireEvent.change(input, { target: { value: "1200" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText("Stored here", { exact: false });
    const [url, request] = fetchMock.mock.calls[1];
    expect(url).toBe("https://ops.example.test/api/ops/backoffice/settings/CANARY_CARD_GRANT_CREDITS");
    expect(request.method).toBe("PUT");
    expect(JSON.parse(request.body)).toEqual({ value: "1200" });
    expect(request.headers["X-Canary-Ops-Token"]).toBe("operator-secret");

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(fetchMock.mock.calls[2][1].method).toBe("DELETE"));
    await screen.findByText(/Not set: off/);
  });

  it("keeps the shown value and reports the reason when a change is refused", async () => {
    fetchMock
      .mockImplementationOnce(() => reply({ store: "loaded", settings: [setting({ value: "1200", source: "database" })] }))
      .mockImplementationOnce(() => reply({ detail: "The highest allowed value is 10000." }, 422));
    render(<RuntimeSettingsPanel connection={connection} />);
    fireEvent.change(await screen.findByLabelText("New value for CANARY_CARD_GRANT_CREDITS"), { target: { value: "50000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The highest allowed value is 10000.");
    expect(screen.getByText("1200")).toBeTruthy();
  });

  it("explains that nothing is editable where the table is not installed", async () => {
    fetchMock.mockImplementationOnce(() => reply({ store: "absent", settings: [setting({ editable: false, value: "500", source: "environment" })] }));
    render(<RuntimeSettingsPanel connection={connection} />);
    expect(await screen.findByText(/not installed on this server/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});
