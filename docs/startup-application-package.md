# Scenewright — Startup program application package

**Status: Draft application copy, October 7, 2026.** This package is for Scenewright; Canary is the internal project name. Product descriptions reflect the checked-in implementation and public copy. Program-specific integrations, milestones, and customer segments below are proposals where identified. Company, founder, and traction facts need the founder's input.

Use the answers below independently. X means the program sponsor, such as Anthropic, Google, or PostHog. Replace bracketed fields when they appear; choose the answer that matches the sponsor and the services you intend to use.

## What are you building?

### One sentence

Scenewright is an AI comic studio that turns manuscripts into complete, lettered comic pages, with authors directing the story, visual style, and cast.

### Short answer — under 50 words

We're building Scenewright, an AI comic studio for authors. It turns prose into an adaptation, establishes the visual style and cast, and generates complete, lettered comic pages. Authors review and revise the work, then export a PDF or CBZ, with shared story and visual references across a series.

### Standard answer — under 150 words

We're building Scenewright, an AI comic studio that helps authors turn their manuscripts into complete, lettered comics.

Turning prose into a comic means deciding what to show, what to say, how to pace the pages, and how to keep characters recognizable. Scenewright brings those steps into one workflow. It builds an editable story bible, drafts an adaptation brief, establishes the visual style and cast, adapts the prose into visual beats and dialogue, and generates full comic pages.

Authors approve key creative decisions, review pages, and request corrections. Projects can use integrated lettering or editable text and balloons; editable lettering can change without regenerating the artwork. Finished parts export as PDF or CBZ, while the series keeps its shared story and visual references.

Our goal is to make comic adaptation accessible to authors who already have a story and want to bring it to a visual audience.

## How will your agent use X?

### Anthropic — under 100 words

We plan to use Claude through Anthropic's API for the narrative tasks in Scenewright: understanding manuscripts, drafting adaptation briefs, turning prose into visual beats and dialogue, and planning comic pages. Each task uses approved story context and produces structured outputs linked to the source text. Authors retain control through approval checkpoints and page review. Program credits would let us evaluate Claude on representative stories and expand its use where it improves source fidelity, narrative coherence, or correction effort. We'd track those outcomes alongside latency and cost per reviewed page.

### Google — under 100 words

We plan to use Gemini on Vertex AI for manuscript understanding and visual generation in Scenewright. Our code already includes Google image-generation integrations. The workflow supplies story context and approved visual references to produce style proofs, cast references, and complete comic pages, which authors review and revise. Google program support would help us evaluate model choices across those tasks, focusing on narrative fidelity, character continuity, page composition, latency, and cost per reviewed page. We would expand usage based on the results and the services covered by the program.

### PostHog — under 100 words

We'll use PostHog to connect Scenewright's agent performance to author outcomes. The product is already instrumented for product analytics, session replay, error tracking, and AI generation telemetry. We can examine where authors stop, which stages fail, and which generated pages lead to corrections or redraws, alongside model latency and cost. Production telemetry excludes manuscript, prompt, and output bodies, while replay masks author text and blocks artwork. Startup credits would fund the underlying analytics and observability usage. We also plan to evaluate a development agent that queries these signals to identify workflow problems and prioritize improvements.

### AgentGrown — under 100 words

I'll use AgentGrown to give my coding agent search and traffic data for scenewright.ink, an AI comic studio for authors. After connecting Search Console and GA4, I'll have the agent research searches such as "turn a novel into a comic," identify pages with impressions but few clicks, and prioritize useful guides, metadata fixes, and internal links. The agent will implement changes in the website repository for review, then use subsequent data to assess changes in rankings, organic traffic, and signups. Program support would help me build a repeatable, evidence-based approach to acquiring authors through search.

### Very short sponsor-specific answers — under 40 words each

- **Anthropic:** We'll evaluate Claude for manuscript understanding, adaptation, and page planning, using structured outputs and author approval checkpoints. Program credits would help us improve narrative fidelity and reduce correction effort.
- **Google:** We'll evaluate Gemini and Vertex AI for story understanding, visual references, and full comic pages. Program support would help us improve continuity, composition, and cost per reviewed page.
- **PostHog:** We'll connect AI generation telemetry with author behavior, errors, and redraw requests to improve Scenewright's workflow. Program support would help us identify production friction and prioritize changes using measured outcomes.

### General answer — under 100 words

Our agent will use [X] for [specific task] within Scenewright's manuscript-to-comic workflow. It will receive the relevant source passages, approved adaptation brief, and story or visual references, then produce [specific output] that the next stage can use. Scenewright saves intermediate results and checks their structure and source references, while authors approve key creative decisions and review the generated pages. We'll evaluate [X] on representative stories, measuring task quality, latency, cost per reviewed page, and correction effort. Program support would fund that evaluation and early production usage.

### For a language-model provider — under 150 words

Our agent will use [X]'s language models to turn prose into a structured comic adaptation. The workflow identifies characters, locations, and story events; drafts an adaptation brief for author approval; writes visual beats, dialogue, and captions; and plans those beats into pages with deliberate pacing and reading order.

Each task receives the relevant manuscript passages and approved story context. The system retains links between the adaptation and its source, validates structured outputs, and saves intermediate work so authors can inspect it and resume production. Authors approve the brief, visual direction, and cast before the workflow advances through those checkpoints, then review the generated pages.

We would use program credits to evaluate [X] on source fidelity, narrative coherence, and page-planning quality, and compare latency and cost across those tasks. The goal is fewer corrections and a more dependable path from manuscript to finished comic.

### For an image-model provider — under 150 words

Our agent will use [X]'s image models to generate visual style proofs, cast references, and complete comic pages. Page requests combine the planned action, composition, and approved visual references so recurring characters and locations have a consistent basis across the story.

We would evaluate [X] for the lettering modes its models support: integrated lettering generates text and balloons with the artwork, while editable lettering keeps the base art separate from the text and balloons. Authors review the generated pages and request corrections to specific issues; artwork corrections produce a new full-page revision.

Program credits would support experiments on character continuity, complex page composition, and correction workflows. We would measure usable-page cost, latency, and the number of redraws needed after human review. A successful API response alone would not count as evidence of visual quality.

### For a cloud or infrastructure provider — under 150 words

Scenewright's agent workflow will use [X] to support long-running comic production jobs and their saved artifacts. A project contains manuscript text, an approved adaptation brief, shared story and visual references, generated page revisions, lettering, and final exports. The application needs durable job dispatch, persistent storage, access controls, and visibility into failures and generation costs.

We would use the program to evaluate [specific X services] for [specific operational need], starting with representative projects and measuring job completion, recovery behavior, storage use, and operating cost. Our current deployment uses one AWS Lightsail application host, persistent project storage, Supabase account and credit metadata, and a PostgreSQL-backed job queue.

The proposed integration would support that workload as it grows. It would preserve saved creative work and author approval checkpoints, with a defined migration and recovery plan for any infrastructure change.

### For a developer-tool or coding-agent program — under 100 words

We would use [X] to help build and maintain Scenewright's adaptation engine, generation integrations, and author-facing studio. Priority tasks include investigating failures, improving stage validation, implementing integrations, and adding focused tests for regressions. Changes would be reviewed and checked with provider-free tests before release. Program support would let us evaluate the tool on real development tasks, measuring time to a reviewed change, regression rate, and maintenance effort. This use concerns the agent helping us develop the product; it is separate from the creative workflow authors use.

## Runware grant application

The following answers match the Runware grant form. The founder confirmed no customer traction and no monthly usage forecast on October 7, 2026. These answers distinguish product progress and intended usage from measured adoption.

### What traction can you point to today?

Scenewright does not have customer traction yet. I have built a working manuscript-to-comic studio with adaptation, visual style and cast direction, full-page generation, page review, lettering, and PDF/CBZ export. A complete development example adapts Krishan Coupland's *Kaitlin Out of Space* into a 52-page comic, providing a concrete demonstration of the workflow. My next step is to validate it with authors and measure whether they can complete adaptations they are happy to share. The evidence today is a working product and a finished demonstration, with customer validation still ahead.

### What are you aiming to build with Runware?

I want to integrate Runware as an image-generation backend for Scenewright, helping authors turn their stories into complete comics. The initial scope is visual style proofs, character and location references, full comic pages, and instructed page corrections. I'll evaluate suitable models using approved visual references and page plans, focusing on recognizable characters, coherent page composition, and preservation of story details. Editable lettering lets authors adjust text and balloons independently of the artwork. My goal is to expand the model choices available in the studio and improve generation speed and cost per reviewed page, while preserving author approval and review throughout production.

### Where does generative AI fit, and what is your expected usage?

Generative AI is central to Scenewright. Language models turn manuscripts into story structure, visual beats, dialogue, and page plans; image models generate style proofs, cast references, and complete comic pages. My initial Runware usage would focus on evaluating image generation and editing models, followed by author pilots. Each adaptation needs an initial generation for every page, plus style and cast references and author-requested corrections. I don't have a reliable monthly volume forecast yet. I'll establish one from pilot activity, tracking generation requests, provider cost, latency, and corrections per reviewed page before expanding usage.

**Usage planning, for internal use:** Monthly requests depend on the number of projects, pages per project, style/cast reference generations, and correction requests. No monthly request volume or dollar spend is claimed before pilot evidence and model selection are available.

## Together AI application

Scenewright currently uses hosted model APIs. The initial Together proposal is serverless inference; no dedicated GPU requirement has been established. The spend and GPU-count brackets below reflect the form values supplied by the founder, not a measured capacity forecast.

### What GPUs do you need?

**Select: Other.** If a description is available: "Serverless inference initially. I don't have a specific dedicated GPU requirement yet; hardware and capacity would be determined after model selection and workload benchmarking."

### What is your monthly GPU spend?

**Select: <$10K**, as supplied by the founder. Do not infer an exact spend from this bracket. Hosted inference charges and directly rented GPU spend are distinct.

### How many GPUs do you need?

No dedicated GPUs are required for the proposed initial serverless integration. If the form requires a range and **1–16** is its smallest available option, use that bracket and clarify in an additional-details field: "My initial requirement is serverless API inference. Dedicated GPU capacity is not yet established; 1–16 is the smallest available form bracket."

### Which model architecture are you using?

Scenewright uses pretrained language models for manuscript understanding, adaptation, and page planning, alongside hosted image-generation models for visual references and complete comic pages. These models are accessed through APIs; I am building the orchestration and author-review workflow rather than training a custom model architecture. For Together, I plan to evaluate supported open-weight language and image-generation models, with final model selection based on narrative fidelity, visual continuity, latency, and cost per reviewed page.

### What's your timeline for deployment?

I plan to begin model evaluation and API integration once access is available. Scenewright already has a working adaptation workflow, so the initial work is to integrate Together and validate suitable models on representative stories. Production rollout would follow successful evaluation and an author pilot. I don't have a committed production deployment date yet.

## Other common application questions

### What problem are you solving?

An author can have a finished story and still face a substantial production task to adapt it into a comic. Prose must become visible actions, dialogue, panel sequences, and page turns, with recognizable characters and locations across the book. Scenewright brings adaptation, visual references, drawing, lettering, review, and export into one workflow that the author can direct.

### Who is it for?

Scenewright is built for authors who want to adapt their own stories into comics. Our proposed initial focus is independent fiction writers starting with a short story or a scene from a longer manuscript. A small first adaptation gives them a concrete way to judge the style, fidelity, and correction effort before producing more of the story.

### What makes it different?

Scenewright's focus is the complete adaptation workflow. It connects source passages to adapted beats, carries approved style and cast references into page generation, and maintains a shared story bible across series parts. Authors can inspect intermediate decisions and revise pages. For editable editions, lettering changes are independent of artwork generation. The product brings these capabilities together around one outcome: a finished comic the author has reviewed and can export.

### Why is this an agent use case?

Making a comic requires a sequence of dependent creative tasks. The adaptation determines what happens and what is said; the page plan determines how readers experience it; drawing uses those decisions and the approved references; finishing packages the reviewed result. Scenewright coordinates model calls and deterministic processing across these stages, saves their outputs, and pauses at author approval checkpoints. This is a staged creative workflow with human direction, rather than a promise of unattended publication.

### What have you built so far?

We've implemented a web studio with manuscript input, story-bible editing, adaptation briefs, style and cast direction, full-page generation, page review and correction, lettering workflows, and PDF/CBZ export. The product supports series with shared story and visual references. A development example adapts Krishan Coupland's *Kaitlin Out of Space* into a 52-page comic, giving reviewers a concrete sequence to inspect alongside the source story.

That example demonstrates product capability. For customer traction, add only verified figures: [active authors], [paying customers], [revenue over a stated period], and [completed customer projects], measured as of [date].

### How do you make money?

Scenewright uses prepaid generation credits. Authors buy credits and spend them on generation and redraws, with approximate estimates shown before supported actions. The current product has no subscription. Cost depends on the selected generation profile, story length, references, and corrections. We plan to measure provider cost and correction effort per reviewed page to understand the economics of completed adaptations.

### Why do you want to join this program?

We're applying to [program] to improve [specific production task] using [X]. Credits would fund a focused evaluation on representative stories and early production use, while technical support would help us resolve [specific integration or quality challenge]. Our proposed milestones are to establish a baseline, compare [X] against it, and ship an integration if it improves quality or operating cost. We would track source fidelity, author correction effort, latency, and cost per reviewed page.

### What will you do over the next three months?

Proposed milestones, to adjust to the program's scope:

1. **Month 1:** Establish a baseline on representative, authorized stories. Record adaptation issues, visual continuity issues, correction effort, latency, and generation cost.
2. **Month 2:** Evaluate [X] on one defined task, integrate it if the results justify the change, and check the workflow through review and export.
3. **Month 3:** Run an author pilot, measure completion and revision behavior, and use that evidence to refine the workflow and its economics.

### Why are you the right founder or team?

I'm [name], a [role/background] with experience in [relevant work]. I started Scenewright because [specific personal motivation or observed customer problem]. I've built [your actual contribution] and learned [specific lesson] from [real development or customer experience]. My next priority is [concrete milestone].

## Supporting materials

Links below come from the product's configured public routes. Verify their live availability before submission.

| Material | Link |
|---|---|
| Product | [Scenewright](https://scenewright.ink) |
| Workflow | [How it works](https://scenewright.ink/how-it-works) |
| Example | [Annotated comic example](https://scenewright.ink/examples/kaitlin-out-of-space) |
| Business model | [Pricing](https://scenewright.ink/pricing) |

For a short demo, show a source passage, the approved brief and cast, several consecutive generated pages, one correction or lettering edit, and the exported result. Consecutive pages make pacing and continuity easier to assess.

## Sponsor reference notes

These notes inform tailoring; they are not part of the copy to paste into forms.

- Together's accelerator includes serverless inference credits, and its serverless offering does not require GPU provisioning. Starting with serverless is a recommendation based on Scenewright's current API workflow and unestablished volume; it is not a hardware benchmark. [Together Startup Accelerator](https://www.together.ai/startup-accelerator), [Together serverless models](https://docs.together.ai/docs/serverless/models).
- Runware's grant form asks for current traction, intended product work, and generative AI usage. Its platform describes reference-driven image generation and prompt-based editing; suitability for complete comic pages still needs evaluation. [Runware grant program](https://runware.ai/grant-program), [Runware documentation](https://runware.ai/docs). The proposed integration is not a claim of existing Runware use; no volume forecast is asserted.
- AgentGrown's published package describes an MCP connection for keyword research, Search Console, GA4, and before/after measurement. The answer proposes using it with the coding agent that maintains Scenewright's website. It does not assert that Search Console, GA4, or AgentGrown are already connected. [AgentGrown package documentation](https://www.npmjs.com/package/agentgrown).
- Anthropic's program supports first-party Claude API use. Its credits cannot be spent through Vertex AI or Bedrock, so the Anthropic answer proposes direct API use. [Claude Startups](https://claude.com/programs/startups).
- The Google answer proposes Gemini and Vertex AI use. Match the requested support to the exact Google program and its covered services before submitting. [Google Cloud AI startup program](https://cloud.google.com/startup/ai).
- PostHog's startup credits cover analytics and AI observability, but exclude several AI tools, including PostHog AI and Replay Vision. The PostHog answer requests support for underlying telemetry usage; agent-driven analysis is identified as proposed work. [PostHog for Startups](https://posthog.com/startups).

## Facts to supply for each application

| Field | Input needed |
|---|---|
| Company | Legal name, incorporation status/date, country, website |
| Founder/team | Names, roles, relevant experience, full-time status |
| Stage | Your description of launch status and current funding |
| Traction | Dated users, paying customers, revenue, pilots, or feedback |
| Program fit | Exact program, X product/service, intended task, integration status |
| Support request | Credit amount or support need and the workload it will fund |
| Form constraints | Character/word limits, deadline, and required attachments |

## Internal evidence notes

These references support the draft and are not application text:

- Product positioning, workflow, pricing model, and the development example: [public product pages](../web/src/pages/ProductPage.tsx).
- Public name, origin, and routes: [public page configuration](../web/src/lib/publicPages.ts).
- Active stages and author approval checkpoints: [pipeline state](../novel_to_comic/src/novel_to_comic/state.py) and [stage registry](../novel_to_comic/src/novel_to_comic/stages/__init__.py).
- Source-linked adaptation, lettering, and series boundaries: [stage contracts](reference/stage-contracts.md).
- Current deployment contract: [deployment](deploy.md).
- Implemented telemetry and production content boundaries: [PostHog and launch learning](reference/observability.md) and [telemetry implementation](../novel_to_comic/src/novel_to_comic/server/telemetry.py).
- Google page-generation integration: [page drawing](../novel_to_comic/src/novel_to_comic/page_drawing.py).

No customer counts, revenue, fundraising, cost savings, or founder credentials have been inferred from the repository. Sponsor answers distinguish existing instrumentation or integrations from proposed use; repository evidence does not establish current live activation or usage volume.
