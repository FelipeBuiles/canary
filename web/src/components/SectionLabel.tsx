export function SectionLabel({
  children,
  tone = "gold",
}: {
  children: string;
  tone?: "gold" | "red";
}) {
  return (
    <div
      className={`inline-flex border-[2px] border-ink-black px-3 py-1 font-meta text-[0.5rem] tracking-[0.18em] ${
        tone === "red"
          ? "bg-hero-red text-bristol"
          : "bg-narrator-gold text-ink-black"
      }`}
    >
      {children}
    </div>
  );
}
