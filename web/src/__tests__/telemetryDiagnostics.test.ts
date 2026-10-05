import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRouteTemplate, beginApiObservation, finishApiObservation, observeApiRequests, safeExceptionMessage } from "../lib/telemetryDiagnostics";
import { maskReplayAttribute, maskReplayText, scrubEvent } from "../telemetry";
import { replayClasses, safeReplayLabel } from "../lib/replayPrivacy";

afterEach(() => { document.body.innerHTML = ""; document.head.querySelectorAll("style").forEach(node => node.remove()); vi.restoreAllMocks(); });

describe("bounded diagnostic context", () => {
  it("correlates requests and retains timing without URLs or response bodies", () => {
    const captured = vi.fn();
    const session = "01234567-89ab-4cde-89ab-0123456789ab";
    observeApiRequests(captured, () => session);
    const observation = beginApiObservation("/projects/UNPUBLISHED_SECRET/parts/part-private/pages/7?token=SECRET", "POST");
    expect(observation.traceparent).toMatch(/^00-[a-f0-9]{32}-[a-f0-9]{16}-01$/);
    expect(observation.route).toBe("/api/projects/:id/parts/:id/pages/:id");
    const response = new Response("PRIVATE BODY", { status: 409, headers: { "X-Request-ID": observation.request_id } });
    const properties = finishApiObservation(observation, response, "draw_preflight_rejected");
    const event = scrubEvent({ event: "api_request_completed", uuid: "test", properties });
    expect(event?.properties).toMatchObject({ request_id: observation.request_id, trace_id: observation.trace_id,
      browser_session_id: session, method: "POST", http_status: 409, error_code: "draw_preflight_rejected" });
    expect(event?.properties.latency_ms).toBeGreaterThanOrEqual(0);
    expect(JSON.stringify(event)).not.toMatch(/UNPUBLISHED_SECRET|PRIVATE BODY|token=/);
    expect(captured).toHaveBeenCalledOnce();
    expect(apiRouteTemplate("//external.invalid/private")).toBe("/api/other");
  });

  it("retains diagnostic templates and stack locations while redacting arbitrary messages", () => {
    const result = scrubEvent({ event: "$exception", uuid: "test", properties: {
      error_code: "draw_preflight_rejected", http_status: 409,
      $exception_list: [{ type: "ApiError", value: "PRIVATE MANUSCRIPT", stacktrace: { frames: [] } }],
    } });
    expect(result?.properties.$exception_list[0].value).toBe("Draw preflight prerequisites were not met");
    expect(JSON.stringify(result)).not.toContain("PRIVATE MANUSCRIPT");
    expect(safeExceptionMessage("Cannot read properties of undefined (reading 'PRIVATE MANUSCRIPT')"))
      .toBe("Cannot read a property of a missing value");
    expect(safeExceptionMessage("PRIVATE MANUSCRIPT")).toBe("[redacted]");
    expect(safeExceptionMessage("anything", "toString")).toBe("[redacted]");
  });
});

describe("replay labels and application CSS", () => {
  it("exposes explicit literal control labels and keeps story/input text masked", () => {
    document.body.innerHTML = '<button data-ph-safe-label="Export"><span id="label">Export</span><input id="input" /></button><p id="story">Export</p>';
    expect(maskReplayText("Export", document.getElementById("label")!)).toBe("Export");
    expect(maskReplayText("Export", document.getElementById("story")!)).toBe("******");
    expect(maskReplayText("Export", document.getElementById("input")!)).toBe("******");
    expect(maskReplayText("PRIVATE MANUSCRIPT", document.getElementById("label")!)).toBe("******* **********");
    expect(safeReplayLabel("PRIVATE MANUSCRIPT")).toBeUndefined();
    expect(safeReplayLabel("Continue in {station}")).toBeUndefined();

    const result = scrubEvent({ event: "$snapshot", uuid: "test", properties: {
      $session_id: "session", $window_id: "window", $snapshot_data: [
        { type: 2, data: { node: { type: 2, id: 1, tagName: "button", attributes: { "data-ph-safe-label": "Export" },
          childNodes: [{ type: 3, id: 2, textContent: "Export" }] } } },
        { type: 3, data: { source: 0, texts: [{ id: 2, value: "Export" }, { id: 2, value: "PRIVATE MANUSCRIPT" }] } },
      ],
    } });
    expect(result?.properties.$snapshot_data[0].data.node.childNodes[0].textContent).toBe("Export");
    expect(result?.properties.$snapshot_data[1].data.texts[0].value).toBe("Export");
    expect(JSON.stringify(result)).not.toContain("PRIVATE MANUSCRIPT");
  });

  it("keeps only classes from trusted stylesheets and reconstructs safe development CSS", () => {
    const trusted = document.createElement("style");
    trusted.setAttribute("data-vite-dev-id", "/app/web/src/index.css");
    trusted.textContent = '.primary { color: red; background-image: url("/api/projects/SECRET/art.png"); } .hover\\:bg-red:hover { color: blue; }';
    document.head.append(trusted);
    const untrusted = document.createElement("style");
    untrusted.textContent = ".SECRET { color: red; }";
    document.head.append(untrusted);
    expect(replayClasses("primary hover:bg-red SECRET")).toBe("primary hover:bg-red");
    expect(maskReplayAttribute("href", "https://external.invalid/assets/app.css")).toBe("[redacted]");
    const result = scrubEvent({ event: "$snapshot", uuid: "test", properties: {
      $session_id: "session", $window_id: "window", $snapshot_data: [{ type: 2, data: { node: {
        type: 2, id: 1, tagName: "style", attributes: { "data-vite-dev-id": "/app/web/src/index.css" },
        childNodes: [{ type: 3, id: 2, textContent: "PRIVATE SNAPSHOT CSS" }],
      } } }],
    } });
    expect(JSON.stringify(result)).toContain("color: red");
    expect(JSON.stringify(result)).not.toMatch(/PRIVATE SNAPSHOT CSS|SECRET|\/app\/web/);
  });
});
