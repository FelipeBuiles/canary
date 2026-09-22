import { BrandMark } from "./BrandMark";

/** Shared masthead identity used by the library and public pages. */
export function BrandIdentity() {
  return (
    <span className="inline-flex shrink-0 items-center gap-2.5">
            <BrandMark className="h-8 w-8 shrink-0" variant="micro" />
            <span className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
              Scenewright
            </span>
            <span className="bg-narrator-gold px-2.5 py-1 font-meta text-[0.54rem] font-bold tracking-[0.12em] text-ink-black">
              BETA
            </span>
    </span>
  );
}
