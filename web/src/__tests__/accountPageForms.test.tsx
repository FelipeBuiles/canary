import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "../pages/AccountPage";
import { I18nProvider } from "../i18n";

const updateUser = vi.hoisted(() => vi.fn());
vi.mock("../lib/supabase", () => ({ supabase: { auth: { updateUser } } }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: { email: "reader@example.com" } }) }));
const openTab = (name: string) => fireEvent.click(screen.getAllByRole("button", { name })[0]!);
const setup = () => render(<I18nProvider><AccountPage /></I18nProvider>);

beforeEach(() => { updateUser.mockReset(); });

describe("Account page forms", () => {
  it("labels the email input and confirms a new address without changing the current address", async () => {
    updateUser.mockResolvedValue({ error: null });
    setup();
    const email = screen.getByLabelText("New email address");
    expect(email.getAttribute("autocomplete")).toBe("email");
    fireEvent.change(email, { target: { value: "next@example.com" } });
    fireEvent.submit(screen.getByRole("form", { name: "Change email" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Check your inbox"));
    expect(updateUser).toHaveBeenCalledExactlyOnceWith({ email: "next@example.com" });
    expect(screen.getByText("reader@example.com")).toBeTruthy();
    expect(email).toHaveProperty("value", "");
  });

  it("keeps typed email and passwords when switching sections", () => {
    setup();
    fireEvent.change(screen.getByLabelText("New email address"), { target: { value: "draft@example.com" } });
    openTab("Password");
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "draft-secret" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "draft-secret" } });
    openTab("Email");
    expect(screen.getByLabelText("New email address")).toHaveProperty("value", "draft@example.com");
    openTab("Password");
    expect(screen.getByLabelText("New password")).toHaveProperty("value", "draft-secret");
    expect(screen.getByLabelText("Confirm new password")).toHaveProperty("value", "draft-secret");
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("submits a matching password through the authenticated account API and clears both fields", async () => {
    updateUser.mockResolvedValue({ error: null });
    setup();
    openTab("Password");
    expect(screen.queryByLabelText(/current password/i)).toBeNull();
    const password = screen.getByLabelText("New password");
    const confirm = screen.getByLabelText("Confirm new password");
    expect(password.getAttribute("autocomplete")).toBe("new-password");
    expect(confirm.getAttribute("autocomplete")).toBe("new-password");
    fireEvent.change(password, { target: { value: "short" } });
    fireEvent.change(confirm, { target: { value: "short" } });
    fireEvent.submit(screen.getByRole("form", { name: "Change password" }));
    expect(updateUser).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("Password must be at least 6 characters.");
    fireEvent.change(password, { target: { value: "new-secret" } });
    fireEvent.change(confirm, { target: { value: "different" } });
    expect(screen.getByRole("button", { name: "Update password" })).toHaveProperty("disabled", true);
    fireEvent.submit(screen.getByRole("form", { name: "Change password" }));
    expect(updateUser).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("Passwords don't match.");
    fireEvent.change(confirm, { target: { value: "new-secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Change password" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Password updated successfully."));
    expect(updateUser).toHaveBeenCalledExactlyOnceWith({ password: "new-secret" });
    expect(password).toHaveProperty("value", "");
    expect(confirm).toHaveProperty("value", "");
  });

  it.each(["Email", "Password"])("recovers from a rejected %s update without discarding the draft", async (tab) => {
    updateUser.mockRejectedValue(new Error("Connection interrupted"));
    setup();
    openTab(tab);
    if (tab === "Email") {
      fireEvent.change(screen.getByLabelText("New email address"), { target: { value: "retry@example.com" } });
    } else {
      fireEvent.change(screen.getByLabelText("New password"), { target: { value: "retry-secret" } });
      fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "retry-secret" } });
    }
    fireEvent.submit(screen.getByRole("form", { name: `Change ${tab.toLowerCase()}` }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Connection interrupted"));
    expect(screen.getByRole("button", { name: `Update ${tab.toLowerCase()}` })).toHaveProperty("disabled", false);
    expect(screen.getByLabelText(tab === "Email" ? "New email address" : "New password"))
      .toHaveProperty("value", tab === "Email" ? "retry@example.com" : "retry-secret");
  });
});
