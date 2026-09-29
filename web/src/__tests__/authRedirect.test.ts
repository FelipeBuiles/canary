import { describe, expect, it } from "vitest";
import { authRedirectUrl } from "../lib/authRedirect";

describe("authentication email destinations", () => {
  it.each(["https://scenewright.ink", "https://www.scenewright.ink", "https://canary-web.fly.dev"])(
    "returns users from %s to the canonical domain", (origin) => {
      expect(authRedirectUrl("/", origin)).toBe("https://scenewright.ink/");
      expect(authRedirectUrl("/?sample=an-education", origin)).toBe("https://scenewright.ink/?sample=an-education");
      expect(authRedirectUrl("/reset-password", origin)).toBe("https://scenewright.ink/reset-password");
    },
  );

  it("keeps local development on its own origin", () => {
    expect(authRedirectUrl("/", "http://localhost:5173")).toBe("http://localhost:5173/");
    expect(authRedirectUrl("/reset-password", "http://127.0.0.1:5173")).toBe("http://127.0.0.1:5173/reset-password");
  });
});
