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
