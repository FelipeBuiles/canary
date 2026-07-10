import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

vi.mock("../api/queries", () => ({
  useShortStories: () => ({ data: [] }),
}));

import { UploadStep } from "../components/wizard/UploadStep";

describe("UploadStep keyboard flow", () => {
  it("uses Enter to advance first, then submit the named project", async () => {
    const user = userEvent.setup();
    const onSubmitImport = vi.fn();

    render(
      <I18nProvider>
        <UploadStep
          onSubmit={() => undefined}
          onSubmitImport={onSubmitImport}
          isPending={false}
          error={null}
        />
      </I18nProvider>,
    );

    await user.click(screen.getByText("USE ANOTHER SOURCE"));
    const source = screen.getByPlaceholderText("e.g. story URL or library code");
    await user.type(source, "the-last-incantation{Enter}");

    expect(screen.getByText("NAME AND START")).toBeTruthy();
    expect(onSubmitImport).not.toHaveBeenCalled();

    const projectName = screen.getByLabelText("PROJECT NAME");
    await user.click(projectName);
    await user.keyboard("{Enter}");

    expect(onSubmitImport).toHaveBeenCalledTimes(1);
    expect(onSubmitImport).toHaveBeenCalledWith(
      "the-last-incantation",
      "The Last Incantation",
      expect.objectContaining({ target_language: "en" }),
    );
  });
});
