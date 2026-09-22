import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { Publication } from "../../api/publications";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";

export function BookPublication({ project, title, ready, onPreview }: { project: string; title: string; ready: boolean; onPreview?: () => void }) {
  const { t } = useI18n();
  const cache = useQueryClient();
  const key = ["publication", project];
  const query = useQuery({ queryKey: key, queryFn: () => apiFetch<Publication | null>(`/projects/${project}/publication`) });
  const [draft, setDraft] = useState<{ title: string; author: string; description: string; allow_feature: boolean } | null>(null);
  const [message, setMessage] = useState("");
  const values = draft ?? { title: query.data?.title ?? title, author: query.data?.author ?? "", description: query.data?.description ?? "", allow_feature: query.data?.allow_feature ?? false };
  const update = (change: Partial<typeof values>) => setDraft({ ...values, ...change });
  const mutation = useMutation({
    mutationFn: (remove: boolean) => apiFetch<Publication | null>(`/projects/${project}/publication`, { method: remove ? "DELETE" : "POST", ...(remove ? {} : { body: JSON.stringify(values) }) }),
    onSuccess: (_result, remove) => { setMessage(t(remove ? "Your book is no longer public." : "Your finished book is now public. Copy the link to share it.")); void cache.invalidateQueries({ queryKey: key }); },
  });
  const url = query.data ? `${window.location.origin}/read/${query.data.id}` : "";
  async function share() {
    try {
      if (navigator.share) await navigator.share({ title: query.data!.title, url });
      else { await navigator.clipboard.writeText(url); setMessage(t("Link copied.")); }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setMessage(t("Copy the public link below to share your book."));
    }
  }
  return <section className="my-8 border-2 border-ink-black bg-bristol p-6" aria-labelledby="share-book-title">
    <h2 id="share-book-title" className="font-display text-2xl">{t("Share your finished book")}</h2>
    <p className="mt-3 max-w-prose font-body">{t("Publish all finished pages for anyone with the link to read and download. Your manuscript and working files stay private. Later edits stay private until you update the published version.")}</p>
    {query.isPending ? <p role="status">{t("Loading…")}</p> : query.isError ? <div role="alert"><p>{t("Sharing settings could not be loaded.")}</p><Button onClick={() => void query.refetch()}>{t("Try again")}</Button></div> : <>
      <form className="mt-5 grid gap-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(false); }}>
        <label className="grid gap-2 font-meta">{t("Public title")}<input required maxLength={160} value={values.title} onChange={e => update({ title: e.target.value })} className="border-2 border-ink-black bg-pulp-paper p-3" /></label>
        <label className="grid gap-2 font-meta">{t("Author credit")}<input required maxLength={120} value={values.author} onChange={e => update({ author: e.target.value })} className="border-2 border-ink-black bg-pulp-paper p-3" /></label>
        <label className="grid gap-2 font-meta">{t("Short description")}<textarea maxLength={600} value={values.description} onChange={e => update({ description: e.target.value })} className="border-2 border-ink-black bg-pulp-paper p-3" /></label>
        <label className="flex min-h-11 items-center gap-3"><input type="checkbox" checked={values.allow_feature} onChange={e => update({ allow_feature: e.target.checked })} />{t("Allow Scenewright to feature this book on the homepage")}</label>
        <p className="font-body text-sm">{t("The public reader includes a Made with Scenewright credit and a closing invitation to create a book.")}</p>
        {!ready && <p>{t("Resolve the edition checks before publishing or updating your book.")}</p>}
        <div className="flex flex-wrap gap-3"><Button variant="outline" disabled={!onPreview} onClick={onPreview}>{t("Preview all pages")}</Button><Button type="submit" disabled={!ready || mutation.isPending || !values.title.trim() || !values.author.trim()}>{mutation.isPending ? t("Saving…") : query.data ? t("Update published version") : t("Publish book")}</Button></div>
      </form>
      {query.data && <div className="mt-6 grid gap-3 border-t-2 border-ink-black pt-5">
        <a className="break-all underline" href={url} target="_blank" rel="noreferrer">{url}</a>
        <div className="flex flex-wrap gap-3"><Button onClick={() => void share()}>{t("Share book")}</Button><Button variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate(true)}>{t("Unpublish")}</Button></div>
      </div>}
    </>}
    {message && <p className="mt-4" role="status">{message}</p>}
    {mutation.error && <p className="mt-4" role="alert">{mutation.error.message}</p>}
  </section>;
}
