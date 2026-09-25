import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { publicationLanguages, type Publication } from "../../api/publications";
import { EntityCard, SectionHeader } from "../composites";
import { FieldLabel, TextAreaField, TextField } from "../ui/Field";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";

export function BookPublication({ project, title, ready, onPreview }: { project: string; title: string; ready: boolean; onPreview?: () => void }) {
  const { t } = useI18n();
  const cache = useQueryClient();
  const key = ["publication", project];
  const query = useQuery({ queryKey: key, queryFn: () => apiFetch<Publication | null>(`/projects/${project}/publication`) });
  const [draft, setDraft] = useState<{ title: string; author: string; description: string; allow_feature: boolean } | null>(null);
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState("");
  const [leftOut, setLeftOut] = useState<string[]>([]);
  const values = draft ?? { title: query.data?.title ?? title, author: query.data?.author ?? "", description: query.data?.description ?? "", allow_feature: query.data?.allow_feature ?? false };
  const update = (change: Partial<typeof values>) => setDraft({ ...values, ...change });
  const mutation = useMutation({
    mutationFn: (remove: boolean) => apiFetch<Publication | null>(`/projects/${project}/publication`, { method: remove ? "DELETE" : "POST", ...(remove ? {} : { body: JSON.stringify(values) }) }),
    onSuccess: (result, remove) => { setLeftOut(Object.keys(result?.unpublished_locales ?? {}).map(code => code.toUpperCase())); setDraft(null); setEditing(false); setMessage(t(remove ? "Your book is no longer public." : "Your finished book is now public. Copy the link to share it.")); void cache.invalidateQueries({ queryKey: key }); },
  });
  const url = query.data ? `${window.location.origin}/read/${query.data.id}` : "";
  const readerLanguages = query.data ? publicationLanguages(query.data) : [];
  async function share() {
    try {
      if (navigator.share) await navigator.share({ title: query.data!.title, url });
      else { await navigator.clipboard.writeText(url); setMessage(t("Link copied.")); }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) { setEditing(true); setMessage(t("Copy the public link below to share your book.")); }
    }
  }
  return <section aria-labelledby="share-book-title">
    <div id="share-book-title">
      <SectionHeader variant="underline" title={t("Share your finished book")}
        description={query.data ? t("Later edits stay private until you update the published version.") : t("Publish all finished pages for anyone with the link to read and download. Your manuscript and working files stay private. Later edits stay private until you update the published version.")} />
    </div>
    {query.isPending ? <p role="status" className="font-body text-sm text-ink-muted">{t("Loading…")}</p> : query.isError ? <div role="alert" className="space-y-3"><p className="font-body text-sm">{t("Sharing settings could not be loaded.")}</p><Button variant="outline" size="sm" onClick={() => void query.refetch()}>{t("Try again")}</Button></div> : <EntityCard>
      {query.data && <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <div className="min-w-0">
          <h3 className="break-words font-display text-xl font-black uppercase leading-tight">{query.data.title}</h3>
          <p className="mt-2 font-meta text-xs text-ink-muted">{query.data.author} · {query.data.pages.length} {t("pages")}</p>
          {readerLanguages.length > 1 && <p className="mt-2 font-body text-sm">{t("Reader languages")}: {readerLanguages.map(item => item.locale === "source" ? t("Original") : item.locale.toUpperCase()).join(" · ")}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <a className="inline-flex min-h-11 items-center px-3 font-meta text-sm font-bold underline underline-offset-4" href={url} target="_blank" rel="noreferrer">{t("Read book")}</a>
          <Button onClick={() => void share()}>{t("Share book")}</Button>
          <Button variant="outline" onClick={() => setEditing(!editing)} aria-expanded={editing}>{t(editing ? "Close details" : "Edit publication")}</Button>
        </div>
      </div>}
      {(!query.data || editing) && <form className={`grid gap-5 ${query.data ? "mt-6 border-t border-ink-black/15 pt-6" : ""}`} onSubmit={(event) => { event.preventDefault(); mutation.mutate(false); }}>
        <div className="grid gap-5 md:grid-cols-2">
          <div><FieldLabel htmlFor={`${project}-public-title`}>{t("Public title")}</FieldLabel><TextField id={`${project}-public-title`} required maxLength={160} value={values.title} onChange={e => update({ title: e.target.value })} /></div>
          <div><FieldLabel htmlFor={`${project}-author-credit`}>{t("Author credit")}</FieldLabel><TextField id={`${project}-author-credit`} required maxLength={120} value={values.author} onChange={e => update({ author: e.target.value })} /></div>
        </div>
        <div><FieldLabel htmlFor={`${project}-description`}>{t("Short description")}</FieldLabel><TextAreaField id={`${project}-description`} maxLength={600} rows={3} value={values.description} onChange={e => update({ description: e.target.value })} /></div>
        <label className="flex min-h-11 items-center gap-3 font-body text-sm"><input type="checkbox" className="h-4 w-4 accent-ink-black" checked={values.allow_feature} onChange={e => update({ allow_feature: e.target.checked })} />{t("Allow Scenewright to feature this book on the homepage")}</label>
        <p className="font-body text-xs leading-5 text-ink-muted">{t("The public reader includes a Made with Scenewright credit and a closing invitation to create a book.")}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!ready || mutation.isPending || !values.title.trim() || !values.author.trim()}>{mutation.isPending ? t("Saving…") : query.data ? t("Update published version") : t("Publish book")}</Button>
          <Button variant="outline" disabled={!onPreview} onClick={onPreview}>{t("Preview all pages")}</Button>
          {!ready && <p className="font-body text-sm text-ink-muted">{t("Resolve the edition checks before publishing or updating your book.")}</p>}
        </div>
      </form>}
      {query.data && editing && <div className="mt-6 grid gap-3 border-t border-ink-black/15 pt-5">
        <a className="break-all font-body text-sm underline" href={url} target="_blank" rel="noreferrer">{url}</a>
        <div className="flex flex-wrap gap-3"><Button variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate(true)}>{t("Unpublish")}</Button></div>
      </div>}
    </EntityCard>}
    {message && <p className="mt-4 font-body text-sm" role="status">{message}</p>}
    {leftOut.length > 0 && <p className="mt-2 font-body text-sm">{t("Not published in {languages}. Readers only see languages where every page has a saved translation that fits.").replace("{languages}", leftOut.join(", "))}</p>}
    {mutation.error && <p className="mt-4 font-body text-sm text-hero-red" role="alert">{mutation.error.message}</p>}
  </section>;
}
