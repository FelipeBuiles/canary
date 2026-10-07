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

void initTelemetry();
installChunkLoadRecovery();


const root = document.getElementById("root")!;
const bootstrap = getPublicBootstrap();
if (bootstrap?.stories) queryClient.setQueryData(["short-stories"], bootstrap.stories, { updatedAt: 0 });
if (bootstrap?.book) queryClient.setQueryData(["public-book", bootstrap.book.id], bootstrap.book, { updatedAt: 0 });
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
if (root.hasAttribute("data-prerendered")) {
  // Keep the complete initial page visible while its route/catalog loads.
  void Promise.all([loadPublicPage(window.location.pathname), loadCatalog(bootstrap?.language ?? "en")])
    .then(() => hydrateRoot(root, app, options));
} else {
  createRoot(root, options).render(app);
}
