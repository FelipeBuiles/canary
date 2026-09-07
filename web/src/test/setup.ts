import { cleanup } from "@testing-library/react";
import { cleanup as cleanupMedia, matchMedia } from "mock-match-media";
import ResizeObserver from "resize-observer-polyfill";
import { afterEach } from "vitest";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, String(value));
  }
}

const storage = new MemoryStorage();
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
Object.defineProperty(window, "localStorage", { configurable: true, value: storage });

// The canvas animation also needs media queries and element resize observation.
Object.defineProperty(globalThis, "matchMedia", { configurable: true, writable: true, value: matchMedia });
Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: matchMedia });
Object.defineProperty(globalThis, "ResizeObserver", { configurable: true, writable: true, value: ResizeObserver });
Object.defineProperty(window, "ResizeObserver", { configurable: true, writable: true, value: ResizeObserver });

afterEach(() => {
  cleanup();
  storage.clear();
  cleanupMedia();
});
