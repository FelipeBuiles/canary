import { isPublicHome } from "./publicPages";

/** Shared loaders let hydration request only the current public route. */
export function loadPublicPage(path: string) {
  if (isPublicHome(path)) return import("../pages/HomePage").then(({ HomePage }) => ({ default: HomePage }));
  if (path === "/legal/terms") return import("../pages/legal/TermsPage").then(({ TermsPage }) => ({ default: TermsPage }));
  if (path === "/legal/privacy") return import("../pages/legal/PrivacyPage").then(({ PrivacyPage }) => ({ default: PrivacyPage }));
  if (path === "/legal/acceptable-use") return import("../pages/legal/AcceptableUsePage").then(({ AcceptableUsePage }) => ({ default: AcceptableUsePage }));
  return import("../pages/ProductPage").then(({ ProductPage }) => ({ default: ProductPage }));
}
