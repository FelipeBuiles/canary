import { useEffect, useRef, useState } from "react";
import { proofImageUrl, type StyleSuggestion } from "../../api/styles";
import { usePress } from "../ui/motion";

/**
 * The displayed source of one proof. A finished redraw reloads with a fresh
 * timestamp and seats with a press; a failed source is not retried on every
 * poll, but a changed source (a model change, a restored sample) is.
 */
export function useProofImage(projectName: string, suggestion: StyleSuggestion, isGenerating: boolean) {
  const sampleUrl = proofImageUrl(projectName, suggestion);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const src = `${sampleUrl}${sampleUrl.includes("?") ? "&" : "?"}t=${timestamp}`;
  const [load, setLoad] = useState({ url: src, hasSample: suggestion.has_sample, failed: false });
  // Model changes can replace a cached preview URL with the saved raw proof.
  // Reset on each source change, including a return to the original model.
  if (load.url !== src || load.hasSample !== suggestion.has_sample) {
    setLoad({ url: src, hasSample: suggestion.has_sample, failed: false });
  }
  const failed = !suggestion.has_sample || (load.url === src && load.failed);
  const wasGenerating = useRef(isGenerating);
  const arrival = usePress(timestamp);

  useEffect(() => {
    const wasGeneratingValue = wasGenerating.current;
    wasGenerating.current = isGenerating;
    if (!wasGeneratingValue || isGenerating) return;
    const timer = window.setTimeout(() => {
      setLoad((current) => ({ ...current, failed: false }));
      setTimestamp(Date.now());
    }, 0);
    return () => window.clearTimeout(timer);
  }, [isGenerating]);

  return {
    src,
    failed,
    arrival,
    onError: () => setLoad((current) => current.url === src ? { ...current, failed: true } : current),
  };
}
