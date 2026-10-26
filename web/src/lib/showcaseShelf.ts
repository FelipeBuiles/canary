/**
 * The showcase books on the front page, in showcase/books folder order.
 * Static so the shelf and its links are in the prerendered HTML; a test
 * checks every entry against its showcase/books manifest.
 */
export interface ShelfBook {
  id: string;
  title: string;
  author: string;
  pages: number;
  cover: string;
}

export const SHOWCASE_SHELF: readonly ShelfBook[] = [
  { id: "d1cb0ec790244ce6849974daa586146b", title: "The Call of Cthulhu", author: "H. P. Lovecraft", pages: 44, cover: "/marketing/home/cover-call-of-cthulhu.webp" },
  { id: "c55d2cfd0ded41089d048f3c019ade13", title: "The Masque of the Red Death", author: "Edgar Allan Poe", pages: 24, cover: "/marketing/home/cover-masque-of-the-red-death.webp" },
  { id: "df3a1b400a444815bddeca430360f0d9", title: "Kaitlin Out of Space", author: "Krishan Coupland", pages: 52, cover: "/marketing/home/cover-kaitlin-out-of-space.webp" },
  { id: "d95ccd64ff414fa9a99c816f128854c2", title: "Elm and Keep", author: "@strnglft", pages: 21, cover: "/marketing/home/cover-elm-and-keep.webp" },
  { id: "c1f2c824e85e4313a804743865296e85", title: "Site-30's Janitor", author: "JanitorCakeworth", pages: 9, cover: "/marketing/home/cover-site-30s-janitor.webp" },
  { id: "0110627cd88244f5933fb11bdd85bf2d", title: "Astronomical", author: "Sophia Light", pages: 21, cover: "/marketing/home/cover-astronomical.webp" },
  { id: "b32d070d85f942278577140e7f55778b", title: "The Monkey's Paw", author: "W. W. Jacobs", pages: 20, cover: "/marketing/home/cover-monkeys-paw.webp" },
];
