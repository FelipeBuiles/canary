import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { StyleSuggestion } from "../api/styles";
import { useProofImage } from "../components/style/useProofImage";
import { refreshImageToken, resetImageTokens, useImageToken } from "../lib/imageRefresh";

afterEach(() => resetImageTokens());

const proof = { id: "style_a", index: 1, label: "Ink", has_sample: true } as StyleSuggestion;

describe("image cache tokens", () => {
  it("keeps an image URL when its room is left and reopened", () => {
    const first = renderHook(() => useProofImage("demo", proof, false));
    const src = first.result.current.src;
    first.unmount();

    const again = renderHook(() => useProofImage("demo", proof, false));
    expect(again.result.current.src).toBe(src);
  });

  it("renews the URL once a redraw finishes", async () => {
    const view = renderHook(({ generating }) => useProofImage("demo", proof, generating), { initialProps: { generating: true } });
    const before = view.result.current.src;
    view.rerender({ generating: false });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(view.result.current.src).not.toBe(before);
  });

  it("shares one token across views and coalesces one event into one change", async () => {
    const roster = renderHook(() => useImageToken("sheet"));
    const stage = renderHook(() => useImageToken("sheet"));
    await act(async () => {
      roster.result.current[1]();
      stage.result.current[1]();
      refreshImageToken("sheet");
    });
    expect(roster.result.current[0]).toBe(1);
    expect(stage.result.current[0]).toBe(1);
  });
});
