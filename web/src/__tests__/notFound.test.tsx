import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { NotFound } from "../pages/NotFound";
import { I18nProvider } from "../i18n";

describe("NotFound", () => {
  it("renders the cutting-room-floor panel with a way back to the Library", () => {
    render(
      <MemoryRouter initialEntries={["/nonsense"]}>
        <I18nProvider>
          <NotFound />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(screen.getByText("THIS PAGE WAS LEFT ON THE CUTTING ROOM FLOOR")).toBeTruthy();
    expect(screen.getByRole("button", { name: "BACK TO THE LIBRARY" })).toBeTruthy();
  });
});
