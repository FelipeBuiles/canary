/** Mirrors Python Pydantic models — keep in sync manually. */
export const STAGE_NAMES = [
    "extract",
    "index",
    "screenplay",
    "panels",
    "prompts",
    "generate",
    "assemble",
];
export const CHECKPOINT_STAGES = new Set(["extract", "index", "generate"]);
