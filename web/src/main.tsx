import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AccountApp } from "./App";
import { initSentry } from "./sentry";
import { installChunkLoadRecovery } from "./lib/chunkLoadRecovery";
import "./index.css";

initSentry();
installChunkLoadRecovery();


createRoot(document.getElementById("root")!).render(
	<StrictMode>
		<AccountApp />
	</StrictMode>,
);
