// Persist only unresolved actions. Reopening the room or reloading must not
// turn a lost HTTP response into another billable action.
export async function pendingAction(account: string, method: string, path: string, body: BodyInit | null | undefined) {
  let content: unknown = body ?? "";
  if (body instanceof FormData) {
    const fields = [];
    for (const [name, value] of body.entries()) {
      fields.push([name, typeof value === "string" ? value : [
        value.name, value.type,
        Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await value.arrayBuffer()))),
      ]]);
    }
    content = fields;
  }
  const bytes = new TextEncoder().encode(JSON.stringify([account, method, path, content]));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const fingerprint = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  const storageKey = `paid-action:v1:${fingerprint}`;
  // Fail closed if durable storage is unavailable: sending without a recoverable
  // receipt would risk a second charge after a reload.
  const key = localStorage.getItem(storageKey) ?? crypto.randomUUID();
  localStorage.setItem(storageKey, key);
  return {
    key,
    complete() {
      if (localStorage.getItem(storageKey) === key) localStorage.removeItem(storageKey);
    },
  };
}
