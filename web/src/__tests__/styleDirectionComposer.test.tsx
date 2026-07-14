import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StyleDirectionComposer } from "../components/style/StyleDirectionComposer";
import { I18nProvider } from "../i18n";

function renderComposer() {
  const onAutomatic = vi.fn();
  const onCustom = vi.fn();
  render(
    <I18nProvider>
      <StyleDirectionComposer
        automaticCost={30}
        onAutomatic={onAutomatic}
        onCustom={onCustom}
      />
    </I18nProvider>,
  );
  return { onAutomatic, onCustom };
}

describe("StyleDirectionComposer", () => {
  it("does not spend until the author chooses a lane and confirms generation", async () => {
    const user = userEvent.setup();
    const { onAutomatic } = renderComposer();

    expect(onAutomatic).not.toHaveBeenCalled();
    expect(screen.getByText("~30 credits")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "CREATE FIVE DIRECTIONS" }));

    expect(onAutomatic).toHaveBeenCalledOnce();
  });

  it("submits one faithful text direction by default", async () => {
    const user = userEvent.setup();
    const { onCustom } = renderComposer();

    await user.click(screen.getByRole("radio", { name: /Bring a direction/i }));
    await user.type(
      screen.getByLabelText("DESCRIBE THE DIRECTION"),
      "Saturated tropical colors and strong black silhouettes",
    );
    await user.click(screen.getByRole("button", { name: "CREATE MY PROOF" }));

    expect(onCustom).toHaveBeenCalledWith({
      direction: "Saturated tropical colors and strong black silhouettes",
      image: null,
      mode: "single",
    });
  });

  it("can request the supplied direction plus four neighbors", async () => {
    const user = userEvent.setup();
    const { onCustom } = renderComposer();

    await user.click(screen.getByRole("radio", { name: /Bring a direction/i }));
    await user.type(screen.getByLabelText("DESCRIBE THE DIRECTION"), "Luminous ink wash");
    await user.click(screen.getByRole("radio", { name: "This direction + four neighbors" }));
    await user.click(screen.getByRole("button", { name: "CREATE FIVE DIRECTIONS" }));

    expect(onCustom).toHaveBeenCalledWith({
      direction: "Luminous ink wash",
      image: null,
      mode: "neighbors",
    });
  });

  it("requires text when the configured image route cannot consume style references", async () => {
    const user = userEvent.setup();
    const onCustom = vi.fn();
    const { container } = render(
      <I18nProvider>
        <StyleDirectionComposer
          imageReferenceSupported={false}
          onAutomatic={() => undefined}
          onCustom={onCustom}
        />
      </I18nProvider>,
    );
    await user.click(screen.getByRole("radio", { name: /Bring a direction/i }));
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["pixels"], "reference.png", { type: "image/png" }));

    expect(screen.getByText(/cannot read style references/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "CREATE MY PROOF" })).toHaveProperty("disabled", true);
    expect(onCustom).not.toHaveBeenCalled();
  });

  it("requires text before deriving neighboring directions from an image", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <I18nProvider>
        <StyleDirectionComposer
          imageReferenceSupported
          onAutomatic={() => undefined}
          onCustom={() => undefined}
        />
      </I18nProvider>,
    );
    await user.click(screen.getByRole("radio", { name: /Bring a direction/i }));
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(input!, new File(["pixels"], "reference.png", { type: "image/png" }));
    await user.click(screen.getByRole("radio", { name: "This direction + four neighbors" }));

    expect(screen.getByText(/Add a short text description/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "CREATE FIVE DIRECTIONS" })).toHaveProperty("disabled", true);
  });
});
