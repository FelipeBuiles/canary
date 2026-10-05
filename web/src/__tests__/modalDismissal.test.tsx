import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDrawer } from "../components/composites/ConfirmDrawer";
import { ConfirmModal } from "../components/composites/ConfirmModal";
import { RerunDrawer } from "../components/composites/RerunDrawer";
import { Sheet } from "../components/composites/Sheet";
import { ImageModal } from "../components/ui/ImageModal";
import { I18nProvider } from "../i18n";

const modalKinds = ["Sheet", "ConfirmModal", "ConfirmDrawer", "RerunDrawer", "ImageModal"] as const;

function renderModal(kind: typeof modalKinds[number]) {
  const onClose = vi.fn();
  const input = <textarea aria-label="Draft text" defaultValue="Original wording" />;
  const modal = {
    Sheet: <Sheet open title="Edit draft" onClose={onClose}>{input}</Sheet>,
    ConfirmModal: <ConfirmModal open title="Delete draft" body="Confirm deletion" confirmInput="Original wording" onClose={onClose} onConfirm={() => undefined} />,
    ConfirmDrawer: <ConfirmDrawer open title="Edit draft" body="Review draft" extraBody={input} onClose={onClose} onConfirm={() => undefined} />,
    RerunDrawer: <RerunDrawer open stageName="Plan" impactStages={[]} extraBody={input} onClose={onClose} onConfirm={() => undefined} />,
    ImageModal: <ImageModal isOpen src="/proof.png" alt="Draft proof" sidebar={input} onClose={onClose} />,
  }[kind];
  render(<I18nProvider>{modal}</I18nProvider>);
  const field = screen.getByRole("textbox") as HTMLInputElement | HTMLTextAreaElement;
  if (kind === "ConfirmModal") fireEvent.change(field, { target: { value: "Original wording" } });
  // ImageModal assigns the dialog role to the backdrop; the others use a panel.
  const backdrop = kind === "ImageModal" ? screen.getByRole("dialog") : screen.getByRole("presentation");
  return { onClose, field, backdrop };
}

describe.each(modalKinds)("%s backdrop dismissal", (kind) => {
  it("keeps the modal and draft when text selection ends on the backdrop", async () => {
    const user = userEvent.setup();
    const { onClose, field, backdrop } = renderModal(kind);

    await user.pointer([
      { keys: "[MouseLeft>]", target: field, offset: 0 },
      { target: backdrop },
      { keys: "[/MouseLeft]", target: backdrop },
    ]);

    expect(onClose).not.toHaveBeenCalled();
    expect(field.value).toBe("Original wording");
    expect(screen.getByRole("textbox")).toBe(field);

    await user.click(backdrop);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("ignores content clicks and gestures that end inside the panel", async () => {
    const user = userEvent.setup();
    const { onClose, field, backdrop } = renderModal(kind);

    await user.click(field);
    await user.pointer([
      { keys: "[MouseLeft>]", target: backdrop, offset: 0 },
      { target: field, offset: 0 },
      { keys: "[/MouseLeft]", target: field, offset: 0 },
    ]);

    expect(onClose).not.toHaveBeenCalled();
  });

  it("dismisses on a deliberate tap on the backdrop", async () => {
    const user = userEvent.setup();
    const { onClose, backdrop } = renderModal(kind);
    await user.pointer([
      { keys: "[TouchA>]", target: backdrop },
      { keys: "[/TouchA]", target: backdrop },
    ]);
    expect(onClose).toHaveBeenCalledOnce();
  });
});

it("ignores a cancelled backdrop gesture", async () => {
  const user = userEvent.setup();
  const { onClose, backdrop } = renderModal("Sheet");
  await user.pointer({ keys: "[MouseLeft>]", target: backdrop });
  fireEvent.pointerCancel(backdrop);
  await user.pointer({ keys: "[/MouseLeft]", target: backdrop });
  expect(onClose).not.toHaveBeenCalled();
});
