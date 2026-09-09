import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import { StateRefRow } from "../pages/rooms/CastRoom";

const alternateAppearance = {
  id: "after_fire",
  label: "After the fire",
  visual_anchor: "Smoke-blackened stonework",
  baseline_affect: null,
  visually_significant: true,
};

function renderRow(kind: "character" | "location", refreshToken = "poll-1") {
  return render(
    <I18nProvider>
      <StateRefRow
        projectName="demo"
        entityId={kind === "character" ? "char_1" : "loc_1"}
        kind={kind}
        states={[alternateAppearance]}
        stageRegenerating
        refreshToken={refreshToken}
      />
    </I18nProvider>,
  );
}

describe.each([
  ["character", "aspect-[64/84]"],
  ["location", "aspect-[16/9]"],
] as const)("StateRefRow %s tile", (kind, aspectClass) => {
  it("reserves the same image frame while each poll checks a missing image", () => {
    const view = renderRow(kind);
    const image = screen.getByAltText("After the fire reference");
    const initialFrame = image.parentElement;

    expect(initialFrame?.className).toContain(aspectClass);

    fireEvent.error(image);
    const missingFrame = screen.getByText("REBUILDING").parentElement;
    expect(missingFrame?.className).toContain(aspectClass);

    view.rerender(
      <I18nProvider>
        <StateRefRow
          projectName="demo"
          entityId={kind === "character" ? "char_1" : "loc_1"}
          kind={kind}
          states={[alternateAppearance]}
          stageRegenerating
          refreshToken="poll-2"
        />
      </I18nProvider>,
    );

    const polledImage = screen.getByAltText("After the fire reference");
    expect(polledImage.parentElement?.className).toContain(aspectClass);
    fireEvent.error(polledImage);
    expect(screen.getByText("REBUILDING").parentElement?.className).toContain(aspectClass);
  });
});

it("keeps two locations with the same state id independent in thumbnail and full-size views", () => {
  render(<I18nProvider>{["loc_1", "loc_2"].map((entityId) => (
    <StateRefRow key={entityId} projectName="demo" entityId={entityId} kind="location"
      states={[alternateAppearance]} stageRegenerating={false} refreshToken="current" />
  ))}</I18nProvider>);
  const thumbnails = screen.getAllByAltText("After the fire reference");
  expect(thumbnails.map((image) => image.getAttribute("src"))).toEqual([
    "/api/projects/demo/files/plates/loc_1/states/after_fire.png?v=current",
    "/api/projects/demo/files/plates/loc_2/states/after_fire.png?v=current",
  ]);
  thumbnails.forEach((thumbnail, index) => {
    fireEvent.click(thumbnail);
    expect(screen.getByAltText("After the fire").getAttribute("src")).toBe(
      `/api/projects/demo/files/plates/loc_${index + 1}/states/after_fire.png?v=current`,
    );
    fireEvent.keyDown(document, { key: "Escape" });
  });
});
