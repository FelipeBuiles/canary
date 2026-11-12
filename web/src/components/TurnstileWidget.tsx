import { useEffect, useRef } from "react";

/** Cloudflare Turnstile, rendered only where a site key is configured (`lib/turnstile`). */
const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileApi {
  render: (container: HTMLElement, options: Record<string, unknown>) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window { turnstile?: TurnstileApi }
}

let scriptLoading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  scriptLoading ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => { scriptLoading = null; reject(new Error("Turnstile failed to load")); };
    document.head.appendChild(script);
  });
  return scriptLoading;
}

interface TurnstileWidgetProps {
  siteKey: string;
  /** The current token, or null while there is none (not solved, expired, or failed). */
  onToken: (token: string | null) => void;
  /** Change this to request a fresh token; each token works for one request. */
  resetSignal: number;
}

export function TurnstileWidget({ siteKey, onToken, resetSignal }: TurnstileWidgetProps) {
  const container = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  const report = useRef(onToken);
  useEffect(() => { report.current = onToken; }, [onToken]);

  useEffect(() => {
    let cancelled = false;
    void loadScript().then(() => {
      if (cancelled || !container.current || !window.turnstile) return;
      widgetId.current = window.turnstile.render(container.current, {
        sitekey: siteKey,
        callback: (token: string) => report.current(token),
        "expired-callback": () => report.current(null),
        "error-callback": () => report.current(null),
      });
    }).catch(() => report.current(null));
    return () => {
      cancelled = true;
      if (widgetId.current && window.turnstile) window.turnstile.remove(widgetId.current);
      widgetId.current = null;
    };
  }, [siteKey]);

  useEffect(() => {
    if (resetSignal > 0 && widgetId.current && window.turnstile) window.turnstile.reset(widgetId.current);
  }, [resetSignal]);

  return <div ref={container} data-testid="turnstile" className="min-h-[65px]" />;
}
