import { useEffect, useState } from "react";

export const SHOW_DEV_CONTENT_KEY = "canary.showDevContent";

const CHANGE_EVENT = "canary:show-dev-content";
const HASH_RE = /\b[a-f0-9]{32,64}\b/gi;
const POSIX_PATH_RE = /(^|[\s"'`(])\/[^\s"'`<>]+/g;
const WINDOWS_PATH_RE = /\b[A-Za-z]:\\[^\s"'`<>]+/g;
const MODEL_NAME_RE =
  /\b(?:black-forest-labs\/)?(?:flux|gpt|claude|gemini|dall-e|sdxl|stable-diffusion)[\w./:-]*\b/gi;
const DEV_KEY_RE = /(model|sha|hash|path|url|file|ref|refs|reference|artifact)/i;

function canUseStorage() {
  return typeof window !== "undefined" && !!window.localStorage;
}

export function readShowDevContent() {
  if (!canUseStorage()) return false;
  const stored = window.localStorage.getItem(SHOW_DEV_CONTENT_KEY);
  // Default is OFF — the machinery (IDs, hashes, paths, model names) is
  // opt-in via Settings → Dev Content. Hide it from the happy path.
  return stored === "1";
}

export function writeShowDevContent(value: boolean) {
  if (!canUseStorage()) return;
  window.localStorage.setItem(SHOW_DEV_CONTENT_KEY, value ? "1" : "0");
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function useShowDevContent() {
  const [showDevContent, setShowDevContentState] = useState(readShowDevContent);

  useEffect(() => {
    const sync = () => setShowDevContentState(readShowDevContent());
    window.addEventListener("storage", sync);
    window.addEventListener(CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(CHANGE_EVENT, sync);
    };
  }, []);

  const setShowDevContent = (value: boolean) => {
    setShowDevContentState(value);
    writeShowDevContent(value);
  };

  return [showDevContent, setShowDevContent] as const;
}

export function redactDevText(text: string) {
  return text
    .replace(WINDOWS_PATH_RE, "[path hidden]")
    .replace(POSIX_PATH_RE, (_match, prefix: string) => `${prefix}[path hidden]`)
    .replace(HASH_RE, "[hash hidden]")
    .replace(MODEL_NAME_RE, "[model hidden]");
}

export function redactDevParameters(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redactDevParameters(item));
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        DEV_KEY_RE.test(key) ? "[hidden]" : redactDevParameters(item),
      ]),
    );
  }

  if (typeof value === "string") {
    return redactDevText(value);
  }

  return value;
}
