import { elementRect, type LetteringElement, type Rect } from "@lettering-engine";

/** Toggle *emphasis* around a selection. An empty selection takes the word at
 * the caret; surrounding or included asterisks are removed instead. Returns the
 * new copy and the selection of the (un)stressed words. */
export function toggleEmphasis(text: string, start: number, end: number) {
  if (start === end) {
    while (start > 0 && /[\p{L}\p{N}'’-]/u.test(text[start - 1])) start--;
    while (end < text.length && /[\p{L}\p{N}'’-]/u.test(text[end])) end++;
  }
  while (start < end && /\s/.test(text[start])) start++;
  while (end > start && /\s/.test(text[end - 1])) end--;
  if (start === end) return { text, start, end };
  if (text[start - 1] === "*" && text[end] === "*")
    return { text: text.slice(0, start - 1) + text.slice(start, end) + text.slice(end + 1), start: start - 1, end: end - 1 };
  if (end - start > 1 && text[start] === "*" && text[end - 1] === "*")
    return { text: text.slice(0, start) + text.slice(start + 1, end - 1) + text.slice(end), start, end: end - 2 };
  return { text: `${text.slice(0, start)}*${text.slice(start, end)}*${text.slice(end)}`, start: start + 1, end: end + 1 };
}

const center = (r: Rect) => ({ x: r.x + r.width / 2, y: r.y + r.height / 2 });
/** Where a follow-on balloon sits when it is joined from far away: just
 * below its lead, a little to the right, inside the page. */
export function joinedPlacement(lead: LetteringElement, follower: LetteringElement): Rect | null {
  const a = elementRect(lead), b = elementRect(follower), ca = center(a), cb = center(b);
  if (Math.hypot(ca.x - cb.x, ca.y - cb.y) < Math.max(a.height, b.height) * 2.2) return null;
  const x = Math.min(1 - follower.placement.width, Math.max(0, a.x + a.width * .32));
  const y = Math.min(1 - follower.placement.height, Math.max(0, a.y + a.height + .012));
  return { ...follower.placement, x, y };
}
