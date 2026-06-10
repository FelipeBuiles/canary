import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { useI18n } from "../i18n";

export function NotFound() {
  const navigate = useNavigate();
  const { t } = useI18n();

  return (
    <div className="benday-paper flex min-h-[60vh] items-center justify-center px-6 py-16">
      <div className="w-full max-w-md border-[2px] border-ink-black bg-bristol p-10 text-center shadow-ink">
        <div className="mx-auto flex aspect-[4/3] w-full max-w-[240px] items-center justify-center border-[2px] border-dashed border-ink-black/20">
          <span className="font-display text-[2.6rem] font-black tracking-[-0.04em] text-ink-black/15">404</span>
        </div>
        <h1 className="mt-6 font-display text-[1.55rem] font-black uppercase leading-[1.05] tracking-[-0.04em] text-ink-black">
          {t("THIS PAGE WAS LEFT ON THE CUTTING ROOM FLOOR")}
        </h1>
        <div className="mt-7 flex justify-center">
          <Button onClick={() => navigate("/")}>{t("BACK TO THE LIBRARY")}</Button>
        </div>
      </div>
    </div>
  );
}
