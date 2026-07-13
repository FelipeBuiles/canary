import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PanelCard } from "../components/PanelCard";
import { I18nProvider } from "../i18n";
import { getImageFailureCopy } from "../lib/imageFailure";

const t = (value: string) => value;

describe("getImageFailureCopy", () => {
  it.each([
    ["provider_blocked", "IMAGE REQUEST BLOCKED"],
    ["rate_limited", "IMAGE SERVICE BUSY"],
    ["shape_mismatch", "WRONG FRAME SHAPE"],
    ["timed_out", "IMAGE SERVICE TIMED OUT"],
    ["service_unavailable", "IMAGE SERVICE UNAVAILABLE"],
    ["configuration_error", "IMAGE SETUP ERROR"],
    ["empty_response", "NO IMAGE RETURNED"],
    ["generation_error", "IMAGE GENERATION FAILED"],
  ])("explains %s failures", (classification, title) => {
    const copy = getImageFailureCopy(t, classification);

    expect(copy.title).toBe(title);
    expect(copy.message).not.toContain("Something went wrong");
    expect(copy.message.length).toBeGreaterThan(30);
  });

  it("preserves a server explanation for an unknown future classification", () => {
    expect(
      getImageFailureCopy(t, "new_provider_case", "The provider returned a refusal.").message,
    ).toBe("The provider returned a refusal.");
  });

  it("shows the reason on the panel card instead of a generic failure label", () => {
    const onQuickRedo = vi.fn();
    render(
      <I18nProvider>
        <PanelCard
          sceneId="scene_001"
          panelNumber={1}
          status="failed"
          imageUrl="/panel.png"
          imageAvailable={false}
          failureClassification="shape_mismatch"
          onQuickRedo={onQuickRedo}
        />
      </I18nProvider>,
    );

    expect(screen.getByText("WRONG FRAME SHAPE")).toBeTruthy();
    expect(screen.getByText(/returned the wrong frame shape/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "QUICK RE-DO panel 01" }));
    expect(onQuickRedo).toHaveBeenCalledOnce();
  });
});
