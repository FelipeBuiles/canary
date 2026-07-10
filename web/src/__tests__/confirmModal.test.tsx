import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmModal } from "../components/composites/ConfirmModal";

describe("ConfirmModal keyboard submission", () => {
  it("submits with Enter once the confirmation input matches", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();

    render(
      <ConfirmModal
        open
        title="Delete project"
        body="This cannot be undone."
        confirmInput="The Last Incantation"
        confirmLabel="Delete project"
        onConfirm={onConfirm}
        onClose={() => undefined}
      />,
    );

    const input = screen.getByPlaceholderText("The Last Incantation");
    await user.type(input, "The Last Incantation{Enter}");

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("does not submit with Enter while the confirmation input is incomplete", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();

    render(
      <ConfirmModal
        open
        title="Delete project"
        body="This cannot be undone."
        confirmInput="The Last Incantation"
        onConfirm={onConfirm}
        onClose={() => undefined}
      />,
    );

    await user.type(screen.getByPlaceholderText("The Last Incantation"), "The Last{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
