import {
  FileText,
  Image as ImageIcon,
  Palette,
  History,
  Download,
  Settings,
  LifeBuoy,
  Plus,
  ArrowRight,
  X,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Check,
  Play,
  Circle,
  AlertTriangle,
  Loader2,
  MessageSquare,
  Cloud,
  Type,
  Trash2,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  FileDown,
  Archive,
  Sparkles,
  Search,
  Eye,
} from "lucide-react";
import { cn } from "../../lib/cn";

export type IconName =
  | "draft"
  | "assets"
  | "styles"
  | "history"
  | "export"
  | "settings"
  | "support"
  | "plus"
  | "arrow-right"
  | "x"
  | "chevron-down"
  | "chevron-left"
  | "chevron-right"
  | "check"
  | "play"
  | "circle"
  | "alert"
  | "loader"
  | "speech"
  | "thought"
  | "type"
  | "trash"
  | "undo"
  | "redo"
  | "zoom-in"
  | "zoom-out"
  | "reset"
  | "pdf"
  | "archive"
  | "sparkles"
  | "search"
  | "eye";

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

const ICON_MAP = {
  draft: FileText,
  assets: ImageIcon,
  styles: Palette,
  history: History,
  export: Download,
  settings: Settings,
  support: LifeBuoy,
  plus: Plus,
  "arrow-right": ArrowRight,
  x: X,
  "chevron-down": ChevronDown,
  "chevron-left": ChevronLeft,
  "chevron-right": ChevronRight,
  check: Check,
  play: Play,
  circle: Circle,
  alert: AlertTriangle,
  loader: Loader2,
  speech: MessageSquare,
  thought: Cloud,
  type: Type,
  trash: Trash2,
  undo: Undo2,
  redo: Redo2,
  "zoom-in": ZoomIn,
  "zoom-out": ZoomOut,
  reset: RotateCcw,
  pdf: FileDown,
  archive: Archive,
  sparkles: Sparkles,
  search: Search,
  eye: Eye,
};

export function Icon({ name, size = 14, className }: IconProps) {
  const LucideIcon = ICON_MAP[name];
  
  if (!LucideIcon) {
    return null;
  }

  return (
    <LucideIcon 
      size={size} 
      className={cn("shrink-0", className)} 
      strokeWidth={1.6}
      aria-hidden="true"
      focusable="false"
    />
  );
}
