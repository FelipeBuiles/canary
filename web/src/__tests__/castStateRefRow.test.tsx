import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { StateRefRow } from "../pages/rooms/CastRoom";

const fixtures = vi.hoisted(() => ({ references: [] as unknown[] }));

vi.mock("../api/client", () => ({
  isNotFoundError: () => false,
  apiFetch: async (path: string) => path.endsWith("/cast/freshness")
    ? { references: fixtures.references }
    : { jobs: [], versions: [], characters: [], locations: [], props: [] },
}));

function TestProviders({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}><I18nProvider>{children}</I18nProvider></QueryClientProvider>;
}

const alternateAppearance = {
  id: "after_fire",
  label: "After the fire",
  visual_anchor: "Smoke-blackened stonework",
  baseline_affect: null,
  visually_significant: true,
};

function renderRow(kind: "character" | "location", refreshToken = "poll-1") {
  return render(
    <TestProviders>
      <StateRefRow
        projectName="demo"
        entityId={kind === "character" ? "char_1" : "loc_1"}
        kind={kind}
        states={[alternateAppearance]}
        stageRegenerating
        refreshToken={refreshToken}
      />
    </TestProviders>,
  );
}

describe.each([
  ["character", "h-12 w-12"],
  ["location", "h-12 w-12"],
] as const)("StateRefRow %s tile", (kind, aspectClass) => {
  it("reserves the same image frame while each poll checks a missing image", () => {
    const view = renderRow(kind);
    const image = screen.getByAltText("After the fire reference");
    const initialFrame = image.parentElement;

    expect(initialFrame?.className).toContain(aspectClass);

    fireEvent.error(image);
    const missingFrame = screen.getByText("Generating appearance…").parentElement?.previousElementSibling;
    expect(missingFrame?.className).toContain(aspectClass);

    view.rerender(
      <TestProviders>
        <StateRefRow
          projectName="demo"
          entityId={kind === "character" ? "char_1" : "loc_1"}
          kind={kind}
          states={[alternateAppearance]}
          stageRegenerating
          refreshToken="poll-2"
        />
      </TestProviders>,
    );

    const polledImage = screen.getByAltText("After the fire reference");
    expect(polledImage.parentElement?.className).toContain(aspectClass);
    fireEvent.error(polledImage);
    expect(screen.getByText("Generating appearance…").parentElement?.previousElementSibling?.className).toContain(aspectClass);
  });
});

it("keeps two locations with the same state id independent in thumbnail and full-size views", () => {
  render(<TestProviders>{["loc_1", "loc_2"].map((entityId) => (
    <StateRefRow key={entityId} projectName="demo" entityId={entityId} kind="location"
      states={[alternateAppearance]} stageRegenerating={false} refreshToken="current" />
  ))}</TestProviders>);
  const thumbnails = screen.getAllByAltText("After the fire reference");
  expect(thumbnails.map((image) => image.getAttribute("src"))).toEqual([
    "/api/projects/demo/files/plates/loc_1/states/after_fire.png?v=current",
    "/api/projects/demo/files/plates/loc_2/states/after_fire.png?v=current",
  ]);
  thumbnails.forEach((thumbnail, index) => {
    fireEvent.click(thumbnail);
    expect(screen.getByAltText("After the fire").getAttribute("src")).toContain(
      `/api/projects/demo/files/plates/loc_${index + 1}/states/after_fire.png?t=`,
    );
    fireEvent.keyDown(document, { key: "Escape" });
  });
});

it("marks a look drawn from an older main image as out of date", async () => {
  fixtures.references = [
    { kind: "characters", entity_id: "char_1", state_id: "after_fire", status: "outdated", reason: "parent_redrawn" },
  ];
  render(<TestProviders><StateRefRow projectName="demo" entityId="char_1" kind="character"
    states={[alternateAppearance]} stageRegenerating={false} refreshToken="current" /></TestProviders>);
  expect(await screen.findByText("Out of date · review & adjust")).toBeTruthy();
  fixtures.references = [];
});

it("shows looks as updating while their main image's job redraws them", () => {
  render(<TestProviders><StateRefRow projectName="demo" entityId="char_1" kind="character"
    states={[alternateAppearance]} stageRegenerating={false} refreshToken="current" redrawing={["after_fire"]} /></TestProviders>);
  expect(screen.getByText("Updating…")).toBeTruthy();
});
