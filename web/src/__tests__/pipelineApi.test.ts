import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAssetRegenEstimate,
  regenLocationState,
} from "../api/pipeline";
import { createStyleDirection, fetchStyleSampleEstimate, generateStyleSamples, generateStyleValidation, setActiveStyle, suggestStyles } from "../api/styles";
import { getFinishPreflight, runFinishPreflight, triggerExport } from "../api/pages";
import { apiFetch } from "../api/client";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async (path: string, options?: RequestInit) => ({ path, options })),
}));

const mockedApiFetch = vi.mocked(apiFetch);

describe("generation API", () => {
  beforeEach(() => {
    mockedApiFetch.mockClear();
  });

  it("serializes cast asset and appearance-state estimates", async () => {
    await fetchAssetRegenEstimate("proj one", "character", "char_001", "winter_coat");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/asset-regen-estimate?asset_type=character&asset_id=char_001&state_id=winter_coat",
    );
  });

  it("regenerates a location appearance through its state endpoint", async () => {
    await regenLocationState("proj one", "great hall", "after fire");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/locations/great%20hall/states/after%20fire/regenerate",
      { method: "POST", paidAction: true },
    );
  });

  it("requests a one-proof style estimate", async () => {
    await fetchStyleSampleEstimate("proj one");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/styles/sample-estimate",
    );
  });

  it("sends a custom text and image direction as multipart data", async () => {
    const image = new File(["pixels"], "mood.webp", { type: "image/webp" });
    await createStyleDirection("proj one", {
      direction: "Luminous ink wash",
      image,
      withNeighbors: true,
    });

    const [, options] = mockedApiFetch.mock.calls[0];
    expect(mockedApiFetch.mock.calls[0][0]).toBe("/projects/proj%20one/styles/direction");
    expect(options?.method).toBe("POST");
    expect(options?.body).toBeInstanceOf(FormData);
    const body = options?.body as FormData;
    expect(body.get("direction_text")).toBe("Luminous ink wash");
    expect(body.get("image")).toBe(image);
    expect(body.get("with_neighbors")).toBe("true");
  });

  it("uses stable ids for seeded suggestions, proof regeneration, and selection", async () => {
    await suggestStyles("proj", "direction-1");
    await generateStyleSamples("proj", ["style-1"]);
    await setActiveStyle("proj", "style-1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/projects/proj/styles/suggest", {
      paidAction: true, method: "POST",
      body: JSON.stringify({ direction_id: "direction-1" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/projects/proj/styles/generate-samples", {
      paidAction: true, method: "POST",
      body: JSON.stringify({ ids: ["style-1"] }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/projects/proj/styles/active", {
      method: "PATCH",
      body: JSON.stringify({ id: "style-1" }),
    });
  });

  it("requests an optional action audition by stable style id", async () => {
    await generateStyleValidation("proj", "style-1");

    expect(mockedApiFetch).toHaveBeenCalledWith("/projects/proj/styles/validation", {
      paidAction: true, method: "POST",
      body: JSON.stringify({ id: "style-1" }),
    });
  });

  it("requests a fresh verified export when force is set", async () => {
    await triggerExport("proj one", "pdf", true);

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/export/?format=pdf&force=1",
      { method: "POST" },
    );
  });

  it("runs Finish preflight without exporting", async () => {
    await runFinishPreflight("proj one");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/export/preflight",
      { method: "POST" },
    );
  });

  it("reads the persisted Finish preflight before requesting a new one", async () => {
    await getFinishPreflight("proj one");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/export/preflight",
    );
  });
});
