import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import { AccountApp } from "./App";
import { initTelemetry, captureUiError } from "./telemetry";
import { installChunkLoadRecovery } from "./lib/chunkLoadRecovery";
import "./index.css";
import { getPublicBootstrap } from "./lib/publicBootstrap";
import { queryClient } from "./api/queryClient";
import { loadPublicPage } from "./lib/publicRoutes";
import { loadCatalog } from "./locales/messages";
import { publicPages } from "./lib/publicPages";
import { readStoredLanguage } from "./i18n";

void initTelemetry();
installChunkLoadRecovery();


const root = document.getElementById("root")!;
const bootstrap = getPublicBootstrap();
if (bootstrap?.stories) queryClient.setQueryData(["short-stories"], bootstrap.stories, { updatedAt: 0 });
if (bootstrap?.book) queryClient.setQueryData(["public-book", bootstrap.book.id], bootstrap.book, { updatedAt: 0 });
const prerendered = root.hasAttribute("data-prerendered");
const options = {
  onCaughtError: captureUiError,
  onUncaughtError: captureUiError,
  onRecoverableError: captureUiError,
};
const app = (
	<StrictMode>
		<AccountApp />
	</StrictMode>
);
// The first render must not suspend on a catalog: render with it ready, so
// the root never shows a loading block between the shell and the app.
// `/` reaches the client unrendered only for a signed-in browser (the app
// shell), which uses the reader's own language.
const path = window.location.pathname;
const startLanguage = (prerendered ? bootstrap?.language : undefined)
  ?? (path === "/" ? undefined : publicPages[path]?.language) ?? readStoredLanguage();
const ready = Promise.all([
  loadCatalog(startLanguage),
  ...(prerendered ? [loadPublicPage(window.location.pathname)] : []),
]);
void ready.then(
  () => prerendered ? hydrateRoot(root, app, options) : createRoot(root, options).render(app),
  (error: unknown) => {
    // A missing chunk must not leave a static page that never becomes
    // interactive. Render client-side; components load what they need.
    captureUiError(error);
    if (prerendered) root.removeAttribute("data-prerendered");
    createRoot(root, options).render(app);
  },
);
