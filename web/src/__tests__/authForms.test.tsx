import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { LoginPage } from "../pages/auth/LoginPage";
import { SignupPage } from "../pages/auth/SignupPage";
import { ResetPasswordPage } from "../pages/auth/ResetPasswordPage";

const auth = vi.hoisted(() => ({ session: null as object | null, loading: false,
  signInWithPassword: vi.fn(), signUp: vi.fn(), resetPasswordForEmail: vi.fn(), updateUser: vi.fn() }));
vi.mock("../lib/supabase", () => ({ supabase: { auth } }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ session: auth.session, loading: auth.loading }) }));
function setup(page: "login" | "signup" | "reset-password" = "login", query = "") {
  return render(<I18nProvider><MemoryRouter initialEntries={[`/${page}${query}`]}><Routes>
    <Route path="/login" element={<LoginPage />} /><Route path="/signup" element={<SignupPage />} />
    <Route path="/reset-password" element={<ResetPasswordPage />} /><Route path="/" element={<p>Studio home</p>} />
  </Routes></MemoryRouter></I18nProvider>);
}
beforeEach(() => {
  auth.session = null; auth.loading = false;
  auth.signInWithPassword.mockReset(); auth.signUp.mockReset();
  auth.resetPasswordForEmail.mockReset(); auth.updateUser.mockReset();
});

describe("Auth forms", () => {
  it("signs in with the typed credentials and recovers from transport failures", async () => {
    auth.signInWithPassword.mockRejectedValueOnce(new Error("Connection interrupted"))
      .mockResolvedValueOnce({ error: null });
    setup();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "author@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Connection interrupted"));
    expect(screen.getByRole("button", { name: "SIGN IN" })).toHaveProperty("disabled", false);
    expect(screen.getByLabelText("Password")).toHaveProperty("value", "secret");
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    await screen.findByText("Studio home");
    expect(auth.signInWithPassword).toHaveBeenLastCalledWith({ email: "author@example.com", password: "secret" });
  });

  it("creates an account with studio metadata and waits for email confirmation", async () => {
    auth.signUp.mockResolvedValue({ error: null });
    setup("signup");
    fireEvent.change(screen.getByLabelText("Studio Name"), { target: { value: "Ink studio" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "author@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Check author@example.com for the confirmation link."));
    expect(auth.signUp).toHaveBeenCalledExactlyOnceWith({ email: "author@example.com", password: "secret", options: { data: { studio_name: "Ink studio" } } });
    expect(screen.queryByText("Studio home")).toBeNull();
  });

  it("retains the shared book referral when creating an account", async () => {
    auth.signUp.mockResolvedValue({ error: null });
    const id = "a".repeat(32);
    setup("signup", `?ref=book-${id}`);
    fireEvent.change(screen.getByLabelText("Studio Name"), { target: { value: "Ink studio" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "author@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    await waitFor(() => expect(auth.signUp).toHaveBeenCalledWith(expect.objectContaining({ options: { data: { studio_name: "Ink studio", referred_by_book: id } } })));
  });

  it("returns a sample reader to the same story after signup", async () => {
    auth.signUp.mockResolvedValue({ error: null });
    setup("signup", "?sample=an-education");
    fireEvent.change(screen.getByLabelText("Studio Name"), { target: { value: "Ink studio" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "author@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    await waitFor(() => expect(auth.signUp).toHaveBeenCalledWith(expect.objectContaining({
      options: {
        data: { studio_name: "Ink studio" },
        emailRedirectTo: `${window.location.origin}/?sample=an-education`,
      },
    })));
  });

  it("sends a reset link to the same-origin recovery page and handles rejection", async () => {
    auth.resetPasswordForEmail.mockRejectedValueOnce(new Error("Try again later"))
      .mockResolvedValueOnce({ error: null });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    expect(auth.resetPasswordForEmail).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "author@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Try again later"));
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("password-reset link"));
    expect(auth.resetPasswordForEmail).toHaveBeenLastCalledWith("author@example.com", { redirectTo: `${window.location.origin}/reset-password` });
  });

  it("keeps password recovery unavailable without an authenticated recovery session", () => {
    setup("reset-password");
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeTruthy();
    expect(auth.updateUser).not.toHaveBeenCalled();
  });

  it("waits for authentication to finish before allowing a recovery update", () => {
    auth.loading = true;
    setup("reset-password");
    expect(screen.getByRole("button", { name: "UPDATE PASSWORD" })).toHaveProperty("disabled", true);
    fireEvent.submit(screen.getByRole("form", { name: "Set a new password" }));
    expect(auth.updateUser).not.toHaveBeenCalled();
  });

  it("requires matching passwords and resets busy state when recovery fails", async () => {
    auth.session = { user: { id: "author" } };
    auth.updateUser.mockRejectedValueOnce(new Error("Recovery expired"))
      .mockResolvedValueOnce({ error: null });
    setup("reset-password");
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-secret" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "different" } });
    fireEvent.submit(screen.getByRole("form", { name: "Set a new password" }));
    expect(screen.getByRole("alert").textContent).toBe("Passwords don't match.");
    expect(auth.updateUser).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "new-secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Set a new password" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Recovery expired"));
    expect(screen.getByRole("button", { name: "UPDATE PASSWORD" })).toHaveProperty("disabled", false);
    fireEvent.submit(screen.getByRole("form", { name: "Set a new password" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Password updated."));
    expect(auth.updateUser).toHaveBeenLastCalledWith({ password: "new-secret" });
    expect(screen.getByRole("button", { name: "UPDATE PASSWORD" })).toHaveProperty("disabled", true);
  });
});
