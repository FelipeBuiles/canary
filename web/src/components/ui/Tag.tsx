import type { HTMLAttributes } from "react";
import { StatusPill } from "./StatusPill";

type TagProps = HTMLAttributes<HTMLSpanElement>;

export function Tag(props: TagProps) {
  return <StatusPill {...props} />;
}
