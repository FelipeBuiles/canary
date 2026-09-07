import { useRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { ConfirmModal } from "../components/composites/ConfirmModal";
import { Select } from "../components/ui/Select";
import { SelectField } from "../components/ui/Field";
import { RoomTabs } from "../components/composites/RoomTabs";

function DialogHarness() {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [nested, setNested] = useState(false);
  useDialogFocus(ref, { enabled: open, onClose: () => setOpen(false) });
  return <>
    <button onClick={() => setOpen(true)}>Open editor</button>
    {open && <div ref={ref} role="dialog" aria-label="Editor">
      <button onClick={() => setOpen(false)}>Close editor</button>
      <button disabled>Unavailable</button>
      <div style={{ display: "none" }}><button>Hidden control</button></div>
      <details><summary>Details</summary><button>Collapsed control</button></details>
      <Select aria-label="Direction" value="a" options={[{ value: "a", label: "Analog" }, { value: "b", label: "Brush" }]} onValueChange={() => undefined} />
      <button onClick={() => setNested(true)}>Delete draft</button>
      <ConfirmModal open={nested} title="Delete draft?" body="This cannot be undone" destructive onClose={() => setNested(false)} onConfirm={() => undefined} />
    </div>}
  </>;
}

describe("shared dialog focus", () => {
  it("keeps keyboard focus inside visible enabled controls and restores the opener", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "Open editor" });
    await user.click(opener);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close editor" }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Delete draft" }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close editor" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("closes the nested dialog first and returns focus without unlocking the outer dialog", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    await user.click(screen.getByText("Open editor"));
    await user.click(screen.getByRole("button", { name: "Delete draft" }));
    expect(document.activeElement).toBe(screen.getAllByRole("button", { name: "Cancel" })[0]);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Editor" })).toBeTruthy();
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Delete draft" }));
  });

  it("allows the portaled select to handle Escape without closing its dialog", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    await user.click(screen.getByText("Open editor"));
    await user.click(screen.getByRole("button", { name: "Direction" }));
    expect(screen.getByRole("listbox")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Editor" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Direction" }));
  });
});

describe("selection controls", () => {
  it("typeaheads past disabled choices and commits with Enter", async () => {
    const user = userEvent.setup();
    const change = vi.fn();
    render(<Select aria-label="Look" value="a" options={[
      { value: "a", label: "Analog" }, { value: "b", label: "Brush", disabled: true }, { value: "c", label: "Charcoal" },
    ]} onValueChange={change} />);
    await user.click(screen.getByRole("button", { name: "Look" }));
    await user.keyboard("c{Enter}");
    expect(change).toHaveBeenCalledWith("c");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("preserves native field naming, required validation and submitted values", () => {
    const change = vi.fn();
    render(<form aria-label="Settings"><label htmlFor="language">Output language</label><SelectField id="language" name="target_language" required defaultValue="" onChange={change} aria-describedby="hint">
      <option value="">Choose</option><option value="fr">French</option><option value="es" disabled>Spanish</option>
    </SelectField><p id="hint">Comic language</p></form>);
    const field = screen.getByLabelText("Output language") as HTMLSelectElement;
    expect(field.checkValidity()).toBe(false);
    fireEvent.change(field, { target: { value: "fr" } });
    expect(field.checkValidity()).toBe(true);
    expect(new FormData(screen.getByRole("form") as HTMLFormElement).get("target_language")).toBe("fr");
    expect(change).toHaveBeenCalledOnce();
  });

  it("announces filters as pressed buttons, with disabled filters unavailable", async () => {
    const user = userEvent.setup();
    const choose = vi.fn();
    render(<RoomTabs ariaLabel="Pages filter" tabs={[
      { key: "all", label: "All", active: true, onClick: choose },
      { key: "failed", label: "Failed", active: false, onClick: choose, disabled: true },
    ]} />);
    expect(screen.getByRole("button", { name: "All", pressed: true })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Failed", pressed: false }));
    expect(choose).not.toHaveBeenCalled();
  });
});
