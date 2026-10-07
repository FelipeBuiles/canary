import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Surface } from "../components/ui/Surface";
import { Button } from "../components/ui/Button";
import { useI18n } from "../i18n";
import { usePublicMetadata } from "../lib/publicMetadata";

export function NotFound() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { pathname } = useLocation();
  usePublicMetadata("Page not found — Scenewright", "This page does not exist.", pathname, undefined, { noindex: true });

  return (
    <div className="flex min-h-[65vh] items-center justify-center bg-pulp-paper px-5 py-12 sm:py-16">
      <Surface padding="none" shadow="ink" className="w-full max-w-xl overflow-hidden">
        <div className="border-b-[2px] border-ink-black bg-narrator-gold px-6 py-5 sm:px-9">
          <span className="font-meta text-xs font-bold uppercase tracking-widest">{t("Page not found")}</span>
        </div>
        <div className="p-6 sm:p-9">
          <div aria-hidden="true" className="font-display text-[5rem] font-black leading-none tracking-[-0.06em] text-ink-black sm:text-[6rem]">404</div>
          <h1 className="mt-5 max-w-[22ch] font-display text-[1.75rem] font-black uppercase leading-[1.05] tracking-[-0.04em] text-ink-black">
            {t("THIS PAGE WAS LEFT ON THE CUTTING ROOM FLOOR")}
          </h1>
          <p className="mt-4 font-body text-base leading-7 text-ink-muted">{t("Please check the address, or return to Scenewright.")}</p>
          <div className="mt-7 flex">
            <Button onClick={() => navigate("/")}><ArrowLeft size={16} aria-hidden="true" />{t("Back to home")}</Button>
          </div>
        </div>
      </Surface>
    </div>
  );
}
