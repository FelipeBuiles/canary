import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { LoginPage } from "../pages/auth/LoginPage";

const auth = vi.hoisted(() => ({ getAuthProviders: vi.fn(), signInWithPassword: vi.fn(), signUp: vi.fn(),
  resetPasswordForEmail: vi.fn(), resets: [] as number[] }));
vi.mock("../lib/supabase", () => ({ supabase: { auth }, getAuthProviders: auth.getAuthProviders }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ session: null, loading: false }) }));
vi.mock("../lib/turnstile", () => ({ useTurnstileSiteKey: () => "site-key", turnstileSiteKey: async () => "site-key" }));
vi.mock("../components/TurnstileWidget", () => ({
  TurnstileWidget: ({ onToken, resetSignal }: { onToken: (token: string | null) => void; resetSignal: number }) => {
    auth.resets.push(resetSignal);
    return <button type="button" onClick={() => onToken(`token-${resetSignal}`)}>Solve check</button>;
  },
}));

function setup(mode: "signin" | "signup") {
  render(<I18nProvider><MemoryRouter initialEntries={["/login"]}><Routes>
    <Route path="/login" element={<LoginPage initialMode={mode} />} /><Route path="/" element={<p>Studio home</p>} />
  </Routes></MemoryRouter></I18nProvider>);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "author@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
}

beforeEach(() => {
  auth.resets.length = 0;
  auth.getAuthProviders.mockReset().mockResolvedValue({ google: false });
  auth.signInWithPassword.mockReset(); auth.signUp.mockReset(); auth.resetPasswordForEmail.mockReset();
});

describe("Auth forms with the bot check configured", () => {
  it("sends nothing until the check is solved, then one token per request", async () => {
    auth.signUp.mockResolvedValueOnce({ error: new Error("Email rate limit exceeded") }).mockResolvedValueOnce({ error: null });
    setup("signup");
    fireEvent.change(screen.getByLabelText("Studio Name"), { target: { value: "Inkwell" } });
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Complete the check below");
    expect(auth.signUp).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Solve check" }));
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    await screen.findByText("Email rate limit exceeded");
    expect(auth.signUp.mock.calls[0][0].options.captchaToken).toBe("token-0");

    // The spent token is not reused: the widget is reset and must be solved again.
    await waitFor(() => expect(auth.resets.at(-1)).toBe(1));
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Complete the check below"));
    expect(auth.signUp).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Solve check" }));
    fireEvent.submit(screen.getByRole("form", { name: "Create account" }));
    await screen.findByText("Check author@example.com for the confirmation link.");
    expect(auth.signUp.mock.calls[1][0].options.captchaToken).toBe("token-1");
  });

  it("passes the token to sign-in and password reset", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: new Error("Invalid login credentials") });
    auth.resetPasswordForEmail.mockResolvedValue({ error: null });
    setup("signin");
    fireEvent.click(screen.getByRole("button", { name: "Solve check" }));
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    await screen.findByText("Invalid login credentials");
    expect(auth.signInWithPassword.mock.calls[0][0].options.captchaToken).toBe("token-0");

    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Complete the check below"));
    expect(auth.resetPasswordForEmail).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Solve check" }));
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await screen.findByText("Check author@example.com for a password-reset link.");
    expect(auth.resetPasswordForEmail.mock.calls[0][1].captchaToken).toBe("token-1");
  });
});
