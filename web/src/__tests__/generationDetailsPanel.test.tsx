import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { GenerationDetailsPanel } from "../components/ui/GenerationDetailsModal";
import { I18nProvider } from "../i18n";
import { SHOW_DEV_CONTENT_KEY } from "../lib/devContent";

const metadata = {
  version: 1,
  kind: "character_ref",
  prompt: "exact provider-bound prompt",
  prompt_sha256: "a".repeat(64),
  parameters: { model: "hidden-model", width: 1024 },
  provenance: {
    request_id: "request-123",
    execution_fingerprint: "b".repeat(64),
    effective_dimensions: { width: 1024, height: 1280 },
  },
};

function renderPanel() {
  return render(
    <I18nProvider>
      <GenerationDetailsPanel metadata={metadata} />
    </I18nProvider>,
  );
}

afterEach(() => localStorage.clear());

describe("GenerationDetailsPanel", () => {
  it("keeps prompt lifecycle concepts out of the author-facing view", () => {
    renderPanel();

    expect(screen.getByText("ABOUT THIS IMAGE")).toBeTruthy();
    expect(screen.getByText("Created from your saved story details and visual direction.")).toBeTruthy();
    expect(screen.queryByText("exact provider-bound prompt")).toBeNull();
    expect(screen.queryByText("EXACT REQUEST & PROVENANCE")).toBeNull();
    expect(screen.queryByText("request-123")).toBeNull();
  });

  it("exposes collapsed request diagnostics only with Dev Content enabled", () => {
    localStorage.setItem(SHOW_DEV_CONTENT_KEY, "1");
    renderPanel();

    expect(screen.getByText("EXACT REQUEST & PROVENANCE")).toBeTruthy();
    expect(screen.getByText("SUBMITTED IMAGE REQUEST")).toBeTruthy();
    expect(screen.getByText("REQUEST PARAMETERS")).toBeTruthy();
    expect(screen.getByText("RESULT PROVENANCE")).toBeTruthy();
  });
});
