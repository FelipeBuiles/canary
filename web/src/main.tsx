import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AccountApp } from "./App";
import { initTelemetry, captureUiError } from "./telemetry";
import { installChunkLoadRecovery } from "./lib/chunkLoadRecovery";
import "./index.css";

void initTelemetry();
installChunkLoadRecovery();


createRoot(document.getElementById("root")!, {
  onCaughtError: captureUiError,
  onUncaughtError: captureUiError,
}).render(
	<StrictMode>
		<AccountApp />
	</StrictMode>,
);
