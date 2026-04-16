import { useState } from "react";
import { Card } from "./ui/Card";
import { Button } from "./ui/Button";

const SFX_ITEMS = ["KRAK!", "THOOM!", "BAM!", "POW!", "SPEECH"];
const BORDER_WEIGHTS = [1, 4, 8];

export function FloatingPalette() {
  const [activeTab, setActiveTab] = useState<"assets" | "properties">("assets");

  return (
    <Card className="w-[200px] shrink-0">
      <div className="flex border-b-[2px] border-ink-black">
        <Button
          variant={activeTab === "assets" ? "primary" : "outline"}
          size="sm"
          className="flex-1"
          onClick={() => setActiveTab("assets")}
        >
          ASSETS
        </Button>
        <Button
          variant={activeTab === "properties" ? "primary" : "outline"}
          size="sm"
          className="flex-1"
          onClick={() => setActiveTab("properties")}
        >
          PROPERTIES
        </Button>
      </div>

      <div className="p-3">
        {activeTab === "assets" ? (
          <div>
            <div className="mb-2 font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
              SFX & BUBBLES
            </div>
            <div className="space-y-1.5">
              {SFX_ITEMS.map((item) => (
                <button
                  key={item}
                  className="w-full border-[2px] border-ink-black bg-pulp-paper px-3 py-2 text-left font-display text-[0.85rem] font-bold tracking-[-0.03em] hover:bg-ghost-shadow"
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <div className="mb-2 font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
                TYPOGRAPHY
              </div>
              <div className="border-[2px] border-ink-black bg-pulp-paper p-2">
                <select className="w-full bg-transparent font-body text-[0.78rem]">
                  <option>Space Grotesk</option>
                  <option>Be Vietnam Pro</option>
                  <option>Lexend</option>
                </select>
              </div>
            </div>
            <div>
              <div className="mb-2 font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
                BORDER WEIGHT
              </div>
              <div className="flex gap-2">
                {BORDER_WEIGHTS.map((w) => (
                  <Button
                    key={w}
                    variant="outline"
                    size="sm"
                    className="flex-1 py-1.5"
                  >
                    {w}px
                  </Button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
                COLOR FILL
              </div>
              <div className="flex gap-2">
                {[
                  "bg-bristol",
                  "bg-hero-red",
                  "bg-pulp-paper",
                  "bg-ink-black",
                  "bg-narrator-gold",
                ].map((color) => (
                  <div
                    key={color}
                    className={`h-6 w-6 cursor-pointer border-[2px] border-ink-black ${color}`}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
