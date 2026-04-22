import { useState } from "react";
import { Button } from "../components/ui/Button";
import { ControlGroup } from "../components/ui/ControlGroup";
import { DestructiveButton } from "../components/ui/DestructiveButton";
import { FieldLabel, SelectField, SwitchField, TextAreaField, TextField } from "../components/ui/Field";
import { Icon } from "../components/ui/Icon";
import { IconButton } from "../components/ui/IconButton";
import { LoadingBlock, StateBlock } from "../components/ui/StateBlock";
import { RerunDrawer } from "../components/ui/RerunDrawer";
import { ShotDiagram } from "../components/ui/ShotDiagram";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusPill } from "../components/ui/StatusPill";
import { Surface, SurfaceHeader } from "../components/ui/Surface";
import { Tag } from "../components/ui/Tag";

const swatches = [
  ["Hero Red", "bg-hero-red", "#b51822"],
  ["Pulp Paper", "bg-pulp-paper", "#fcfaed"],
  ["Bristol", "bg-bristol", "#ffffff"],
  ["Narrator Gold", "bg-narrator-gold", "#fae361"],
  ["Archive Sage", "bg-archive-sage", "#4a7c59"],
  ["Ink", "bg-ink-black", "#1b1c15"],
  ["Surface Container", "bg-surface-container", "#f0eee1"],
  ["Secondary", "bg-secondary-container", "#d3e4ff"],
];

export function PrimitiveReference() {
  const [rerunOpen, setRerunOpen] = useState(false);
  return (
    <div className="space-y-8">
      <Surface padding="md">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <StatusPill tone="red">DEV ONLY</StatusPill>
            <h1 className="mt-4 display-headline">Primitive Reference</h1>
            <p className="mt-4 lead-pulp max-w-[58ch]">
              A working board for the Narrative Frame primitives: surfaces, controls,
              fields, state blocks, and status treatments.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="primary">Primary Action</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
          </div>
        </div>
      </Surface>

      <section className="grid gap-5 xl:grid-cols-[1fr_1fr]">
        <Surface>
          <SurfaceHeader
            kicker="TONAL STACKING"
            title="Surfaces"
            actions={<StatusPill tone="gold">PAPER SHADOW</StatusPill>}
          />
          <div className="grid gap-4 p-4 md:grid-cols-2">
            <Surface padding="md" shadow="paper-sm">
              <div className="ui-kicker">BRISTOL</div>
              <div className="ui-title mt-1">Panel Card</div>
              <p className="mt-3 text-[0.82rem] leading-6 text-ink-black/65">
                Default paper surface with a mechanical offset shadow.
              </p>
            </Surface>
            <Surface padding="md" tone="container" shadow="ink-sm" benday>
              <div className="ui-kicker">BEN-DAY</div>
              <div className="ui-title mt-1">Texture Field</div>
              <p className="mt-3 text-[0.82rem] leading-6 text-ink-black/65">
                Useful for workbenches, rails, and secondary editing zones.
              </p>
            </Surface>
          </div>
        </Surface>

        <Surface>
          <SurfaceHeader kicker="ACTION PANELS" title="Buttons & Groups" />
          <div className="space-y-4 p-4">
            <ControlGroup label="LETTERING">
              <Button variant="secondary" size="sm">
                <Icon name="speech" /> Speech
              </Button>
              <Button variant="secondary" size="sm">
                <Icon name="thought" /> Thought
              </Button>
              <IconButton icon="undo" label="Undo" />
              <IconButton icon="redo" label="Redo" />
            </ControlGroup>
            <div className="flex flex-wrap gap-2">
              <Button size="xs">Extra Small</Button>
              <Button size="sm">Small</Button>
              <Button size="md">Medium</Button>
              <Button size="lg">Large Button</Button>
            </div>
          </div>
        </Surface>
      </section>

      <section className="grid gap-5 xl:grid-cols-[1fr_1fr]">
        <Surface>
          <SurfaceHeader kicker="DIALOGUE BOX" title="Fields" />
          <div className="grid gap-4 p-4 md:grid-cols-2">
            <div>
              <FieldLabel htmlFor="primitive-title">Comic Theme</FieldLabel>
              <TextField id="primitive-title" defaultValue="golden-age noir" />
            </div>
            <div>
              <FieldLabel htmlFor="primitive-language">Output Language</FieldLabel>
              <SelectField id="primitive-language" defaultValue="en">
                <option value="en">English</option>
                <option value="es">Español</option>
                <option value="fr">Français</option>
              </SelectField>
            </div>
            <div className="md:col-span-2">
              <FieldLabel htmlFor="primitive-notes">Notes</FieldLabel>
              <TextAreaField
                id="primitive-notes"
                defaultValue="Preserve visual anchors exactly. Keep text out of generated panel images."
              />
            </div>
            <div>
              <FieldLabel>Dev Mode</FieldLabel>
              <SwitchField checked onCheckedChange={() => {}} label="Dev Mode" />
            </div>
          </div>
        </Surface>

        <Surface>
          <SurfaceHeader kicker="METADATA" title="Tags & Status" />
          <div className="space-y-4 p-4">
            <div className="flex flex-wrap gap-2">
              <StatusPill tone="neutral">Neutral</StatusPill>
              <StatusPill tone="red">Failed</StatusPill>
              <StatusPill tone="gold">Queued</StatusPill>
              <StatusPill tone="sage">Accepted</StatusPill>
              <StatusPill tone="ink">Locked</StatusPill>
              <StatusPill tone="pulp">Draft</StatusPill>
            </div>
            <div className="flex flex-wrap gap-2">
              <Tag>scene_001</Tag>
              <Tag>wide shot</Tag>
              <Tag>visual anchor</Tag>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <StateBlock
                minHeight="min-h-[180px]"
                title="Not Available"
                description="This room is not ready yet."
                icon="draft"
              />
              <LoadingBlock label="LOADING PANEL GALLERY..." />
            </div>
          </div>
        </Surface>
      </section>

      <Surface>
        <SurfaceHeader
          kicker="ASYNC / DESTRUCTIVE"
          title="Loading & Rerun"
          actions={<StatusPill tone="red">NEW</StatusPill>}
        />
        <div className="space-y-6 p-4">
          <div>
            <div className="ui-kicker mb-2">SKELETON</div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Skeleton aspect="4/3" />
              <Skeleton aspect="4/3" />
              <Skeleton aspect="4/3" />
            </div>
          </div>
          <div>
            <div className="ui-kicker mb-2">SHOT DIAGRAM</div>
            <div className="flex flex-wrap gap-4">
              {["extreme-wide", "wide", "medium-close", "close-up", "extreme-close", "?"].map(
                (s) => (
                  <ShotDiagram key={s} shot={s} />
                ),
              )}
            </div>
          </div>
          <div>
            <div className="ui-kicker mb-2">DESTRUCTIVE ACTION</div>
            <div className="flex flex-wrap items-center gap-3">
              <DestructiveButton size="xs">↺ Rerun XS</DestructiveButton>
              <DestructiveButton size="sm">↺ Rerun Sm</DestructiveButton>
              <DestructiveButton size="md">↺ Rerun Md</DestructiveButton>
              <Button variant="outline" size="sm" onClick={() => setRerunOpen(true)}>
                Open Rerun Drawer
              </Button>
            </div>
          </div>
        </div>
      </Surface>

      <RerunDrawer
        open={rerunOpen}
        stageName="Extract"
        impactStages={["index", "screenplay", "panels", "prompts", "generate", "assemble"]}
        estimatedCost="~$4.10"
        costIsPlaceholder
        itemsAtRisk="46 generated panels will be lost."
        onConfirm={() => setRerunOpen(false)}
        onClose={() => setRerunOpen(false)}
      />

      <Surface padding="md" benday>
        <div className="section-rule">
          <span>SECTION 99</span>
          <span className="text-ink-black/45">//</span>
          <span>COLOR SYSTEM</span>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {swatches.map(([name, bgClass, value]) => (
            <div key={name} className="border-[2px] border-ink-black bg-bristol p-3 shadow-paper-sm">
              <div className={`h-16 border-[2px] border-ink-black ${bgClass}`} />
              <div className="mt-3 ui-title">{name}</div>
              <div className="mt-1 font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/50">
                {value}
              </div>
            </div>
          ))}
        </div>
      </Surface>
    </div>
  );
}
