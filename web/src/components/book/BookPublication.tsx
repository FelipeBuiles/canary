import { ErrorNotice } from "../composites/ErrorNotice";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink } from "lucide-react";
import { apiFetch } from "../../api/client";
import { publicationLanguages, type OwnedPublication } from "../../api/publications";
import { FieldLabel, TextAreaField, TextField } from "../ui/Field";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";
import { projectPath, seriesPath, splitProjectKey } from "../../api/projectScope";

/** Sharing, sized for the Book panel: the live link once published, a short form before. */
export function BookPublication({ project, title, ready, onPreview }: { project: string; title: string; ready: boolean; onPreview?: () => void }) {
  const { t } = useI18n();
  const cache = useQueryClient();
  const { id, part } = splitProjectKey(project);
  const key = ["publication", id];
  const [replaceConfirmed, setReplaceConfirmed] = useState(false);
  const query = useQuery({ queryKey: key, queryFn: () => apiFetch<OwnedPublication | null>(`${seriesPath(project)}/publication`) });
  const [draft, setDraft] = useState<{ title: string; author: string; description: string; allow_feature: boolean } | null>(null);
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState("");
  const [copied, setCopied] = useState(false);
  const [leftOut, setLeftOut] = useState<string[]>([]);
  const values = draft ?? { title: query.data?.title ?? title, author: query.data?.author ?? "", description: query.data?.description ?? "", allow_feature: query.data?.allow_feature ?? false };
  const update = (change: Partial<typeof values>) => setDraft({ ...values, ...change });
  const replacesPart = !!query.data && query.data.source_part_id !== part;
  const mutation = useMutation({
    mutationFn: (remove: boolean) => apiFetch<OwnedPublication | null>(`${remove ? seriesPath(project) : projectPath(project)}/publication`, { method: remove ? "DELETE" : "POST", ...(remove ? {} : { body: JSON.stringify({ ...values, expected_publication_version: query.data?.version }) }) }),
    onSuccess: (result, remove) => { setLeftOut(Object.keys(result?.unpublished_locales ?? {}).map(code => code.toUpperCase())); setDraft(null); setReplaceConfirmed(false); setEditing(false); setMessage(t(remove ? "Your book is no longer public." : "Your finished book is now public. Copy the link to share it.")); void cache.invalidateQueries({ queryKey: key }); },
  });
  const url = query.data ? `${window.location.origin}/read/${query.data.id}` : "";
  const readerLanguages = query.data ? publicationLanguages(query.data) : [];
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setMessage(t("Link copied."));
    } catch {
      setEditing(true);
      setMessage(t("Copy the public link below to share your book."));
    }
  }
  return <section aria-labelledby="share-book-title">
    <div className="flex items-center justify-between gap-3">
      <h3 id="share-book-title" className="font-meta text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-ink-muted">{t("Share")}</h3>
      {query.data && <span className="inline-flex items-center gap-1.5 font-meta text-xs font-semibold text-ready"><span aria-hidden="true" className="size-1.5 bg-ready" />{t("Published")}</span>}
    </div>
    {query.isPending ? <p role="status" className="mt-3 font-body text-sm text-ink-muted">{t("Loading…")}</p> : query.isError ? <div role="alert" className="mt-3 space-y-3"><p className="font-body text-sm">{t("Sharing settings could not be loaded.")}</p><Button variant="outline" size="sm" onClick={() => void query.refetch()}>{t("Try again")}</Button></div> : <>
      {query.data && <div className="mt-3">
        <div className="flex items-stretch border border-ink-black/15">
          <a className="min-w-0 flex-1 truncate px-3 py-2 font-meta text-xs text-ink-black hover:underline" href={url} target="_blank" rel="noreferrer" title={url}>{url.replace(/^https?:\/\//, "")}</a>
          <button type="button" onClick={() => void copyLink()}
            className="inline-flex shrink-0 items-center gap-1.5 border-l border-ink-black/15 px-3 font-meta text-xs font-semibold text-ink-black transition-colors hover:bg-ink-black hover:text-pulp-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red">
            {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}{t("Copy link")}
          </button>
        </div>
        {query.data.source_part_title && <p className="mt-2 font-body text-xs text-ink-muted">{t("Published part")}: {query.data.source_part_title}</p>}
        {readerLanguages.length > 1 && <p className="mt-2 font-body text-xs text-ink-muted">{t("Reader languages")}: {readerLanguages.map(item => item.locale === "source" ? t("Original") : item.locale.toUpperCase()).join(" · ")}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-x-4">
          <a className="inline-flex min-h-9 items-center gap-1.5 font-meta text-xs font-semibold underline decoration-ink-black/25 underline-offset-4 hover:decoration-ink-black" href={url} target="_blank" rel="noreferrer">{t("Open reader page")}<ExternalLink size={12} aria-hidden="true" /></a>
          <button type="button" onClick={() => setEditing(!editing)} aria-expanded={editing}
            className="inline-flex min-h-9 items-center font-meta text-xs font-semibold underline decoration-ink-black/25 underline-offset-4 hover:decoration-ink-black">{t(editing ? "Close details" : "Edit details")}</button>
        </div>
      </div>}
      {!query.data && <p className="mt-2 font-body text-xs leading-5 text-ink-muted">{t("Anyone with the link can read and download it. Your manuscript stays private.")}</p>}
      {(!query.data || editing) && <form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); mutation.mutate(false); }}>
        <div><FieldLabel htmlFor={`${project}-public-title`}>{t("Public title")}</FieldLabel><TextField id={`${project}-public-title`} required maxLength={160} value={values.title} onChange={e => update({ title: e.target.value })} /></div>
        <div><FieldLabel htmlFor={`${project}-author-credit`}>{t("Author credit")}</FieldLabel><TextField id={`${project}-author-credit`} required maxLength={120} value={values.author} onChange={e => update({ author: e.target.value })} /></div>
        <div><FieldLabel htmlFor={`${project}-description`}>{t("Short description")}</FieldLabel><TextAreaField id={`${project}-description`} maxLength={600} rows={2} value={values.description} onChange={e => update({ description: e.target.value })} /></div>
        <label className="flex items-start gap-2.5 font-body text-xs leading-5"><input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-ink-black" checked={values.allow_feature} onChange={e => update({ allow_feature: e.target.checked })} />{t("Allow Scenewright to feature this book on the homepage")}</label>
        {replacesPart && <label className="flex items-start gap-2.5 font-body text-xs leading-5"><input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-ink-black" checked={replaceConfirmed} onChange={e => setReplaceConfirmed(e.target.checked)} />{t("Replace the series public book with this part")}</label>}
        <p className="font-body text-xs leading-5 text-ink-muted">{t("The public reader includes a Made with Scenewright credit and a closing invitation to create a book.")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="secondary" disabled={!ready || (replacesPart && !replaceConfirmed) || mutation.isPending || !values.title.trim() || !values.author.trim()}>{mutation.isPending ? t("Saving…") : query.data ? t("Update published version") : t("Publish book")}</Button>
          {onPreview && <Button variant="outline" onClick={onPreview}>{t("Preview all pages")}</Button>}
        </div>
        {!ready && <p className="font-body text-xs leading-5 text-ink-muted">{t("Resolve the edition checks before publishing or updating your book.")}</p>}
      </form>}
      {query.data && editing && <div className="mt-3 border-t border-ink-black/10 pt-3">
        <Button variant="outline" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate(true)}>{t("Unpublish")}</Button>
      </div>}
    </>}
    {message && <p className="mt-3 font-body text-xs" role="status">{message}</p>}
    {leftOut.length > 0 && <p className="mt-2 font-body text-xs">{t("Not published in {languages}. Readers only see languages where every page has a saved translation that fits.", { languages: leftOut.join(", ") })}</p>}
    {mutation.error && <ErrorNotice error={mutation.error} operation="save" />}
  </section>;
}
