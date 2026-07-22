import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchRegenEstimate,
  fetchAssetRegenEstimate,
  getGenerationRequest,
  previewGenerationRequest,
  prepareGenerationRequest,
  regenPanel,
  regenPanelWithInstruction,
  regenLocationState,
} from "../api/pipeline";
import { createStyleDirection, fetchStyleSampleEstimate, generateStyleSamples, generateStyleValidation, setActiveStyle, suggestStyles } from "../api/styles";
import { triggerExport } from "../api/pages";
import { apiFetch } from "../api/client";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async (path: string, options?: RequestInit) => ({ path, options })),
}));

const mockedApiFetch = vi.mocked(apiFetch);

describe("panel regeneration API", () => {
  beforeEach(() => {
    mockedApiFetch.mockClear();
  });

  it("sends image model alias on quick regen", async () => {
    await regenPanel("proj one", "scene/one", 3, "image-quality");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/regen?scene_id=scene%2Fone&panel_number=3&image_model_alias=image-quality",
      { method: "POST" },
    );
  });

  it("omits image model alias when using project default", async () => {
    await regenPanel("proj", "scene_001", 1, null);

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj/regen?scene_id=scene_001&panel_number=1",
      { method: "POST" },
    );
  });

  it("sends image model alias on instructed regen", async () => {
    await regenPanelWithInstruction("proj", "scene_001", 2, "make it easier", "image-balanced");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj/regen-instructed",
      {
        method: "POST",
        body: JSON.stringify({
          scene_id: "scene_001",
          panel_number: 2,
          instruction: "make it easier",
          image_model_alias: "image-balanced",
        }),
      },
    );
  });

  it("includes image model alias in regen estimate requests", async () => {
    await fetchRegenEstimate("proj", "scene_001", 4, "image-fast");

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj/regen-estimate?scene_id=scene_001&panel_number=4&image_model_alias=image-fast",
    );
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
      { method: "POST" },
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
      method: "POST",
      body: JSON.stringify({ direction_id: "direction-1" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/projects/proj/styles/generate-samples", {
      method: "POST",
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
      method: "POST",
      body: JSON.stringify({ id: "style-1" }),
    });
  });

  it("labels preview requests with the non-paid dev-content switch", async () => {
    await previewGenerationRequest("proj one", "scene/one", 3, "image-quality", true);

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/generation-requests/preview?scene_id=scene%2Fone&panel_number=3&image_model_alias=image-quality&dev_content=1",
    );
  });

  it("uses the authoritative request record for exact Dev Content reads", async () => {
    await getGenerationRequest("proj", "request-1", true);
    await prepareGenerationRequest("proj", "scene_001", 1, null);

    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      1,
      "/projects/proj/generation-requests/request-1?dev_content=1",
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      2,
      "/projects/proj/generation-requests/prepare",
      {
        method: "POST",
        body: JSON.stringify({
          scene_id: "scene_001",
          panel_number: 1,
        }),
      },
    );
  });

  it("sends the explicit issue override for export anyway", async () => {
    await triggerExport("proj one", "pdf", true);

    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/projects/proj%20one/export/?format=pdf&allow_issues=true",
      { method: "POST" },
    );
  });
});
