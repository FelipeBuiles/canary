import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImageModal } from "../components/ui/ImageModal";
import { RegenAction } from "../components/composites/RegenAction";
import { I18nProvider } from "../i18n";

afterEach(() => {
  document.body.style.overflow = "";
  vi.restoreAllMocks();
});

describe("ImageModal", () => {
  it("keeps its scroll lock and key listener stable across parent rerenders", () => {
    const addListener = vi.spyOn(window, "addEventListener");
    const removeListener = vi.spyOn(window, "removeEventListener");
    const firstClose = vi.fn();
    const latestClose = vi.fn();
    const { rerender } = render(
      <ImageModal isOpen onClose={firstClose} src="/plate.png" alt="Location plate" />,
    );

    expect(document.body.style.overflow).toBe("hidden");
    expect(addListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(1);

    rerender(
      <ImageModal isOpen onClose={latestClose} src="/plate.png" alt="Location plate" />,
    );

    expect(removeListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(0);
    expect(addListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(1);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(firstClose).not.toHaveBeenCalled();
    expect(latestClose).toHaveBeenCalledOnce();
  });

  it("lets Escape close a regeneration confirmation without closing the image", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <I18nProvider>
        <ImageModal
          isOpen
          onClose={onClose}
          src="/plate.png"
          alt="Location plate"
          sidebar={(
            <RegenAction
              assetLabel="Location plate"
              cost={{ estimate_credits: 4, reserved_credits: null, reservation_multiplier: 1, confidence: "low_variance" }}
              onRegenerate={() => undefined}
              allowInstruction={false}
            />
          )}
        />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: /TRY ANOTHER VERSION · ~4 credits/i }));
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
});
