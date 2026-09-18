import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getBookLetteringStyle } from "../../api/lettering";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { BookStyleEditor } from "./LetteringEditor";
import "./lettering.css";

export function BookLetteringPanel({ project, disabled, onClose }: {
  project: string;
  disabled: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n(), client = useQueryClient();
  const query = useQuery({ queryKey: ["book-lettering-style", project], queryFn: () => getBookLetteringStyle(project), refetchOnWindowFocus: false, staleTime: 0 });
  if (query.isPending) return <p role="status">{t("Opening lettering…")}</p>;
  if (query.isError) return <div role="alert"><p>{query.error.message}</p><Button variant="outline" onClick={() => void query.refetch()}>{t("Try again")}</Button><Button variant="outline" onClick={onClose}>{t("Cancel")}</Button></div>;
  return <section className="lettering-editor" aria-label={t("Design the book lettering")}>
    <p className="lettering-hint">{t("Edit narration, dialogue, thoughts and effects before drawing pages. Artwork and framing references stay text-free.")}</p>
    <BookStyleEditor project={project} initial={query.data.style} disabled={disabled} onClose={onClose} onApplied={async () => {
      await client.invalidateQueries({ predicate: query => query.queryKey.includes(project) });
      onClose();
    }} />
  </section>;
}
