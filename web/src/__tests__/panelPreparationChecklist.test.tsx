import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PanelPreparationChecklist } from "../components/composites/PanelPreparationChecklist";
import { I18nProvider } from "../i18n";
import type { PanelPreparationState } from "../lib/panelPreparation";

const runningPreparation: PanelPreparationState = {
  completedCount: 1,
  isReady: false,
  failedStage: null,
  runningStage: "plan",
  blockedByStage: null,
  steps: [
    { stage: "adapt", state: "done", itemsDone: 12, itemsTotal: 12 },
    { stage: "plan", state: "running", itemsDone: 4, itemsTotal: 12 },
    { stage: "storyboard", state: "waiting", itemsDone: 0, itemsTotal: 0 },
    { stage: "direct", state: "waiting", itemsDone: 0, itemsTotal: 0 },
  ],
};

const storageValues = new Map<string, string>();
const storage: Storage = {
  get length() {
    return storageValues.size;
  },
  clear: () => storageValues.clear(),
  getItem: (key) => storageValues.get(key) ?? null,
  key: (index) => Array.from(storageValues.keys())[index] ?? null,
  removeItem: (key) => storageValues.delete(key),
  setItem: (key, value) => storageValues.set(key, value),
};

function renderChecklist(preparation: PanelPreparationState) {
  return render(
    <I18nProvider>
      <PanelPreparationChecklist preparation={preparation} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: storage,
  });
  storage.clear();
});

afterEach(cleanup);

describe("PanelPreparationChecklist", () => {
  it("shows the upstream Cast failure instead of claiming the press is running", () => {
    renderChecklist({
      ...runningPreparation,
      completedCount: 0,
      runningStage: null,
      blockedByStage: "cast",
      steps: runningPreparation.steps.map((step) => ({
        ...step,
        state: "waiting",
        itemsDone: 0,
        itemsTotal: 0,
      })),
    });

    expect(screen.getByRole("heading", { name: "CAST NEEDS ATTENTION" })).toBeTruthy();
    expect(screen.getByText("Finish the interrupted cast references before preparing panels.")).toBeTruthy();
    expect(screen.queryByText("You can leave this page — preparation continues in the background.")).toBeNull();
  });

  it("shows one stable checklist with local progress only on the running step", () => {
    renderChecklist(runningPreparation);

    expect(screen.getByRole("heading", { name: "PREPARING YOUR PANELS" })).toBeTruthy();
    expect(screen.getByText("1 OF 4 STEPS COMPLETE")).toBeTruthy();
    expect(screen.getByText("4 / 12 SCENES")).toBeTruthy();
    expect(screen.getByText("You can leave this page — preparation continues in the background.")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("becomes a ready state while preserving all four completed steps", () => {
    renderChecklist({
      completedCount: 4,
      isReady: true,
      failedStage: null,
      runningStage: null,
      blockedByStage: null,
      steps: runningPreparation.steps.map((step) => ({ ...step, state: "done" })),
    });

    expect(screen.getByRole("heading", { name: "READY TO DRAW" })).toBeTruthy();
    expect(screen.getByText("4 OF 4 STEPS COMPLETE")).toBeTruthy();
    expect(screen.getAllByText("DONE")).toHaveLength(4);
  });

  it("renders the approved copy in Spanish", () => {
    storage.setItem("canary.uiLanguage", "es");
    renderChecklist(runningPreparation);

    expect(screen.getByRole("heading", { name: "PREPARANDO TUS VIÑETAS" })).toBeTruthy();
    expect(screen.getByText("1 DE 4 PASOS COMPLETADOS")).toBeTruthy();
    expect(screen.getByText("Planificar páginas y viñetas")).toBeTruthy();
  });

  it("renders the approved copy in French", () => {
    storage.setItem("canary.uiLanguage", "fr");
    renderChecklist(runningPreparation);

    expect(screen.getByRole("heading", { name: "PRÉPARATION DE TES CASES" })).toBeTruthy();
    expect(screen.getByText("1 SUR 4 ÉTAPES TERMINÉES")).toBeTruthy();
    expect(screen.getByText("Planifier les pages et les cases")).toBeTruthy();
  });
});
