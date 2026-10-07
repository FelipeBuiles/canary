import { StrictMode } from "react";
import { renderToReadableStream } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { loadCatalog } from "./locales/messages";
import { loadPublicPage } from "./lib/publicRoutes";
import { publicPages, publicSchema, homePaths, isPublicHome } from "./lib/publicPages";
import { setPublicBootstrap, type PublicBootstrap } from "./lib/publicBootstrap";

export { publicPages, publicSchema, homePaths, isPublicHome };
export { publicSearchMetadata } from "./lib/publicPages";
/** Build-time only. Uses the same components and Suspense boundaries as App. */
export async function renderPublicPage(path: string, bootstrap: PublicBootstrap) {
  const language = publicPages[path].language;
  await loadCatalog(language);
  setPublicBootstrap(bootstrap);
  await loadPublicPage(path);
  const client = new QueryClient();
  if (bootstrap.stories) client.setQueryData(["short-stories"], bootstrap.stories);
  const stream = await renderToReadableStream(<StrictMode><QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>
    <App />
  </MemoryRouter></QueryClientProvider></StrictMode>);
  await stream.allReady;
  const markup = await new Response(stream).text();
  client.clear();
  return markup;
}
