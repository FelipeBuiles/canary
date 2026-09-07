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
  it("uses the latest close callback after a parent rerender", () => {
    const firstClose = vi.fn();
    const latestClose = vi.fn();
    const { rerender } = render(
      <I18nProvider>
        <ImageModal isOpen onClose={firstClose} src="/plate.png" alt="Location plate" />
      </I18nProvider>,
    );


    rerender(
      <I18nProvider>
        <ImageModal isOpen onClose={latestClose} src="/plate.png" alt="Location plate" />
      </I18nProvider>,
    );


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

    await user.click(screen.getByRole("button", { name: /TRY ANOTHER VERSION about 4 credits/i }));
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });


  it("moves focus into the dialog and restores it to the opener", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const opener = document.createElement("button");
    opener.textContent = "Open proof";
    document.body.appendChild(opener);
    opener.focus();

    const { rerender } = render(
      <I18nProvider>
        <ImageModal isOpen onClose={onClose} src="/proof.png" alt="Style proof" />
      </I18nProvider>,
    );

    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" }));

    rerender(
      <I18nProvider>
        <ImageModal isOpen={false} onClose={onClose} src="/proof.png" alt="Style proof" />
      </I18nProvider>,
    );
    expect(document.activeElement).toBe(opener);
    opener.remove();
    await user.keyboard("{Escape}");
  });
});
