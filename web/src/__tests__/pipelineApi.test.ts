import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchRegenEstimate,
  getGenerationRequest,
  previewGenerationRequest,
  prepareGenerationRequest,
  regenPanel,
  regenPanelWithInstruction,
} from "../api/pipeline";
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
});
