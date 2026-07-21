import { expect, test, vi } from "vitest";
import { installChunkLoadRecovery } from "../lib/chunkLoadRecovery";

class MemoryStorage implements Pick<Storage, "getItem" | "setItem"> {
  private values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

test("reloads once when a deployed chunk has disappeared", () => {
  const target = new EventTarget();
  const storage = new MemoryStorage();
  const reload = vi.fn();
  installChunkLoadRecovery({ target, storage, reload, now: () => 10_000 });

  const event = new Event("vite:preloadError", { cancelable: true });
  target.dispatchEvent(event);

  expect(event.defaultPrevented).toBe(true);
  expect(reload).toHaveBeenCalledOnce();
});

test("does not enter a reload loop for repeated stale-chunk errors", () => {
  const target = new EventTarget();
  const storage = new MemoryStorage();
  const reload = vi.fn();
  installChunkLoadRecovery({ target, storage, reload, now: () => 10_000 });

  target.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));
  target.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));

  expect(reload).toHaveBeenCalledOnce();
});
