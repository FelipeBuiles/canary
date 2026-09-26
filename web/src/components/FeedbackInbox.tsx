import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { fetchFeedback, updateFeedback, type OperatorConnection, type CustomerFeedback } from "../api/operator";
import { Button } from "./ui/Button";

export function FeedbackInbox({ connection }: { connection: OperatorConnection }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const key = ["operator-feedback", connection.baseUrl];
  const query = useQuery({ queryKey: key, queryFn: () => fetchFeedback(connection), enabled: Boolean(connection.token) });
  const change = useMutation({
    mutationFn: ({ item, status }: { item: CustomerFeedback; status: CustomerFeedback["status"] }) => updateFeedback(connection, item, status),
    onSuccess: () => { setError(""); void queryClient.invalidateQueries({ queryKey: key }); },
    onError: () => setError("Could not update feedback. Try again."),
  });
  return <section className="space-y-4">
    <div className="flex items-center justify-between"><h2 className="font-display text-2xl font-bold">Private feedback</h2><Button variant="outline" size="sm" onClick={() => void query.refetch()}>Refresh</Button></div>
    <p className="text-sm text-ink-muted">Latest 200 submissions. Review the underlying problem before deciding what to build.</p>
    {query.isPending && <p>Loading feedback…</p>}
    {(query.isError || error) && <p role="alert">{error || "Could not load feedback. Check the connection and database migration."}</p>}
    {query.data?.items.length === 0 && <p>No feedback yet.</p>}
    {query.data?.items.map(item => <article key={`${item.user_id}:${item.id}`} className="border-2 border-ink-black/20 bg-pulp-paper p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><strong>{item.category}</strong><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleDateString()}</time></div>
      <p className="my-3 whitespace-pre-wrap break-words">{item.message}</p>
      <p className="text-xs text-ink-muted">Account: {item.user_id}{item.project_id ? ` · Project: ${item.project_id}` : ""}</p>
      <label className="mt-3 flex items-center gap-2 text-sm">Status<select value={item.status} disabled={change.isPending} onChange={event => change.mutate({ item, status: event.target.value as CustomerFeedback["status"] })} className="border border-ink-black p-2">
        <option value="new">New</option><option value="reviewed">Reviewed</option><option value="planned">Planned</option><option value="resolved">Resolved</option>
      </select></label>
    </article>)}
  </section>;
}
