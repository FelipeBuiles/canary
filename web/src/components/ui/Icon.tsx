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
  Check,
  Play,
  Circle,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { cn } from "../../lib/cn";

type IconName =
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
  | "check"
  | "play"
  | "circle"
  | "alert"
  | "loader";

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
  check: Check,
  play: Play,
  circle: Circle,
  alert: AlertTriangle,
  loader: Loader2,
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
    />
  );
}
