import { Link, useLocation } from "react-router-dom";
import { BrandIdentity } from "../components/BrandIdentity";
import { responsiveMarketingImage } from "../lib/marketingImages";
import { publicPages } from "../lib/publicPages";
import type { ReactNode } from "react";

const navigation = [
  ["/how-it-works", "How it works"], ["/pricing", "Pricing"], ["/samples", "Sample stories"],
  ["/examples/kaitlin-out-of-space", "Comic example"], ["/about", "About"],
] as const;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mt-10"><h2 className="mb-4 font-display text-2xl font-bold leading-tight">{title}</h2><div className="space-y-4">{children}</div></section>;
}
function Workflow() {
  return <>
    <p>Scenewright is an AI-assisted comic studio for authors. It adapts prose into lettered comic pages while you direct the visual style, characters, and final review. Start with one scene before committing to a longer adaptation.</p>
    <Section title="1. Choose a scene and confirm its rights"><p>Upload an EPUB, PDF, or TXT file, or choose a <Link to="/samples">licensed sample story</Link>. Select a short passage with a clear setting, a manageable cast, and an action or emotional change. Use material you own or have permission to adapt.</p></Section>
    <Section title="2. Direct the look and cast"><p>Review the adaptation brief, choose a visual style, and approve the cast references. These references help the pages share a visual identity. For a series, the style, cast, and story bible carry across its parts.</p></Section>
    <Section title="3. Adapt, draw, and review"><p>The studio turns the prose into visual beats and page plans, then generates full comic pages. Check the action, faces, costumes, locations, reading order, and text against your original scene. Use targeted redraws when a page needs correction.</p><p>Continuity references reduce drift, but they do not guarantee identical faces or perfect lettering. Human review is part of the workflow.</p></Section>
    <Section title="4. Finish and export"><p>Projects choose integrated or editable lettering at creation. Integrated lettering arrives in the generated art; editable lettering can be adjusted independently in the page editor. Review the finished pages, then export PDF or CBZ.</p><p>Check the <Link to="/pricing">credit estimates</Link> before generation and redraws. A longer manuscript and more corrections can require more credits.</p></Section>
  </>;
}
function Pricing() {
  return <>
    <p>Scenewright uses prepaid credits for generation. There is no subscription, and purchased credits do not expire. You see an approximate credit estimate before supported generation actions.</p>
    <Section title="Credit packs"><div className="overflow-x-auto"><table className="w-full border-collapse text-left"><caption className="mb-3 text-left text-sm">Current pack prices in US dollars. Confirm the price shown at checkout before buying.</caption><thead><tr className="border-b-2 border-ink-black"><th className="p-3">Pack</th><th className="p-3">Credits</th><th className="p-3">Price</th></tr></thead><tbody>{[["Starter", "1,200", "US$12"], ["Standard", "3,000", "US$30"], ["Creator", "7,500", "US$70"], ["Studio", "18,000", "US$150"]].map(([name, credits, price]) => <tr key={name} className="border-b border-ink-black/20"><th className="p-3 font-semibold">{name}</th><td className="p-3">{credits}</td><td className="p-3">{price}</td></tr>)}</tbody></table></div></Section>
    <Section title="How much does a comic cost?"><p>A credit pack buys generation capacity. It does not promise a fixed number of finished pages. The cost depends on the selected generation profile, scene length, references, and the redraws or other generation actions you choose.</p><p>Use the estimate shown for each action, such as “~N credits,” to plan your spend. Start with a short scene, review the result, and expand once you are happy with its look.</p></Section>
    <Section title="What should I check before buying?"><p>Read the <Link to="/how-it-works">workflow</Link> and inspect a <Link to="/examples/kaitlin-out-of-space">comic example</Link>. Generated pages can need correction. Check the <Link to="/legal/terms">terms of service</Link> for payment and refund conditions.</p><p><Link to="/signup">Create an account</Link> to see your balance, current packs, and generation estimates.</p></Section>
  </>;
}
function Guide() {
  return <>
    <p>To turn a novel into a comic, start by adapting one scene into visible actions, dialogue, and page turns. Establish the cast and visual style before generating pages, then review the sequence as a reader. A full novel usually needs more selection and compression than a short excerpt.</p>
    <Section title="Choose a scene that works on the page"><p>Look for a clear beginning and ending: an arrival, an argument, a discovery, or a decision. A scene with one location and a small cast is easier to evaluate than an entire chapter that moves between viewpoints.</p><p>Resolve the source rights first. Owning a copy of a book does not automatically give you adaptation rights. Licensed samples identify their source and license so you can check the applicable conditions.</p></Section>
    <Section title="Convert prose into visual beats"><p>Mark what changes physically: a door opens, someone looks away, or an object changes hands. Separate those actions from thoughts and exposition. Decide which ideas need a caption, which belong in dialogue, and which can be shown without text.</p><p>Give the reader enough space to understand each action. A reveal often works better after a page turn; a fast exchange may work across several smaller beats. Review the adaptation against the source so compression does not change the scene’s meaning.</p></Section>
    <Section title="Establish visual references"><p>Set the character silhouettes, clothing, important props, and location details. Choose a visual style that supports the tone. Compare later pages against those references, especially when the same character appears under different lighting or at a different scale.</p></Section>
    <Section title="Review the comic, not just each image"><p>Read consecutive pages in order. Check who is speaking, whether an action connects across a page turn, whether a prop changes hands consistently, and whether all dialogue remains readable. Inspect faces, hands, costume details, and unintended text at full size.</p><p>Redraw a page when its art needs correction. For projects with editable lettering, adjust display text in the editor and inspect the exported result. A successful export alone does not establish visual quality.</p></Section>
    <Section title="Try the process on a real example"><p>Compare the <Link to="/samples?story=kaitlin-out-of-space">original Kaitlin Out of Space story</Link> with our <Link to="/examples/kaitlin-out-of-space">annotated comic example</Link>. Then follow the <Link to="/how-it-works">Scenewright workflow</Link> with a short scene from your own manuscript.</p></Section>
  </>;
}
function Example() {
  return <>
    <p>This development example adapts <em>Kaitlin Out of Space</em> by Krishan Coupland into a 52-page comic. A figure in a scorched spacesuit arrives in an older woman’s garden; the story follows the visitor’s gradual change. The example demonstrates the studio’s output and gives you pages to inspect.</p>
    <p><Link to="/samples?story=kaitlin-out-of-space">Read the complete source story</Link> · <Link to="/read/df3a1b400a444815bddeca430360f0d9">Read the finished comic</Link></p>
    <Section title="Compare three points in the adaptation"><div className="grid gap-8 sm:grid-cols-3">{[
      [1, "Establish the scene", "Compare the opening page with the source’s setting and arrival. Check how much information the composition communicates before you read the dialogue."],
      [12, "Check continuity", "Compare the recurring figures and locations with the opening pages. Inspect costume, scale, face, and spatial relationships rather than relying on a thumbnail."],
      [34, "Read the sequence", "Read the pages around this point in the finished comic. Check pacing, dialogue order, and whether visual changes follow the source story."],
    ].map(([number, title, note]) => {
      const src = `/marketing/kaitlin-page-${String(number).padStart(2, "0")}.webp`;
      return <figure key={number}><a href={src}><img src={src} {...responsiveMarketingImage(src, "(max-width: 640px) 90vw, 30vw")} alt={`Kaitlin Out of Space comic adaptation, page ${number}`} loading="lazy" decoding="async" /></a><figcaption className="mt-4 text-sm"><strong>Page {number}: {title}</strong><p className="mt-2">{note}</p></figcaption></figure>;
    })}</div></Section>
    <Section title="Source, license, and limits"><p>The original story is published by <a href="https://krishancoupland.co.uk/portfolio/kaitlin-out-of-space/">Krishan Coupland</a> under <a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0</a>. The author credit and source remain visible in the sample library.</p><p>These pages are a curated demonstration. They are not a promise that every generated scene will match their quality. Character details and lettering can still need correction; inspect the complete sequence and your own exports.</p></Section>
  </>;
}
function About() {
  return <>
    <p>Scenewright is a web-based comic adaptation studio for authors. It helps turn written scenes into lettered comic pages with AI-assisted adaptation and image generation. Authors direct the visual style and cast, review the pages, and export a PDF or CBZ book.</p>
    <Section title="Made for an author’s workflow"><p>The studio combines story adaptation, character and style references, page planning, drawing, and finishing. It is developed in the Canary project. Scenewright is the public product name and scenewright.ink is its website.</p><p>Start with a scene from your own manuscript or a licensed sample. The <Link to="/how-it-works">workflow</Link>, <Link to="/pricing">pricing page</Link>, and <Link to="/examples/kaitlin-out-of-space">comic example</Link> show what to expect.</p></Section>
    <Section title="What needs your judgment"><p>AI-generated adaptations can compress or misread prose, and image generation can introduce inconsistencies. You remain responsible for reviewing the meaning, art, text, and rights before sharing or publishing your book.</p></Section>
    <Section title="Contact and policies"><p>For product questions, write to <a href="mailto:hello@scenewright.ink">hello@scenewright.ink</a>. For legal or rights questions, write to <a href="mailto:legal@scenewright.ink">legal@scenewright.ink</a>.</p><p>Read the <Link to="/legal/terms">terms of service</Link>, <Link to="/legal/privacy">privacy policy</Link>, and <Link to="/legal/acceptable-use">acceptable use and reporting policy</Link>.</p></Section>
  </>;
}
const content: Record<string, { heading: string; body: () => ReactNode }> = {
  "/how-it-works": { heading: "Turn a scene into comic pages.", body: Workflow },
  "/pricing": { heading: "Generation credits. No subscription.", body: Pricing },
  "/guides/turn-a-novel-into-a-comic": { heading: "How to turn a novel into a comic.", body: Guide },
  "/examples/kaitlin-out-of-space": { heading: "Kaitlin Out of Space: a comic adaptation.", body: Example },
  "/about": { heading: "A comic studio for authors.", body: About },
};
export function ProductPage() {
  const { pathname } = useLocation();
  const page = content[pathname];
  if (!page) return null;
  const Body = page.body;
  return <div className="min-h-svh bg-pulp-paper text-ink-black">
    <a href="#product-main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-bristol focus:p-3">Skip to content</a>
    <header className="border-b-2 border-ink-black bg-bristol px-5 py-4 sm:px-8"><div className="mx-auto flex max-w-[1100px] flex-wrap items-center justify-between gap-5"><Link to="/"><BrandIdentity /></Link><nav aria-label="Scenewright" className="flex flex-wrap gap-5 text-sm">{navigation.map(([path, label]) => <Link key={path} to={path} aria-current={pathname === path ? "page" : undefined}>{label}</Link>)}</nav><Link to="/signup" className="inline-flex min-h-11 items-center border-2 border-ink-black bg-hero-red px-4 font-meta text-xs font-bold text-bristol shadow-ink-sm hover:bg-[#94141c]">Create account ↗</Link></div></header>
    <main id="product-main" className="mx-auto max-w-[1100px] px-5 py-12 sm:px-8"><article className="mx-auto max-w-[80ch] font-body leading-7 [&_a]:underline [&_a]:underline-offset-4"><p className="font-meta text-xs uppercase tracking-widest text-hero-red">Scenewright / {publicPages[pathname]?.title.split(" | ")[0]}</p><h1 className="mb-8 mt-5 font-display text-4xl font-black leading-tight tracking-tight sm:text-6xl">{page.heading}</h1><Body /></article></main>
    <footer className="mx-auto flex max-w-[1100px] flex-wrap gap-6 border-t border-ink-black/20 px-5 py-8 text-sm sm:px-8"><Link to="/guides/turn-a-novel-into-a-comic">Novel to comic guide</Link><Link to="/legal/terms">Terms</Link><Link to="/legal/privacy">Privacy</Link><Link to="/legal/acceptable-use">Acceptable use</Link><span>© 2026 Scenewright</span></footer>
  </div>;
}
