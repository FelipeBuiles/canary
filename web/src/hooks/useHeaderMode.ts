import { useState, useEffect } from "react";

const STORAGE_KEY = "canary.ui.headerMode";

function read(): "compact" | "showcase" {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "showcase" ? "showcase" : "compact";
  } catch {
    return "compact";
  }
}

function write(value: "compact" | "showcase") {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // ignore
  }
}

/** Returns the current header mode and a toggle function. */
export function useHeaderMode() {
  const [mode, setMode] = useState<"compact" | "showcase">(read);

  useEffect(() => {
    write(mode);
  }, [mode]);

  const toggle = () => setMode((m) => (m === "compact" ? "showcase" : "compact"));

  return { isCompact: mode === "compact", toggle };
}
