import type { ButtonHTMLAttributes } from "react";
import { Button } from "./Button";
import { Icon, type IconName } from "./Icon";
import { cn } from "../../lib/cn";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  label: string;
  variant?: "primary" | "secondary" | "outline";
  size?: "xs" | "sm" | "md" | "lg";
}

export function IconButton({
  icon,
  label,
  variant = "outline",
  size = "sm",
  className,
  ...props
}: IconButtonProps) {
  return (
    <Button
      variant={variant}
      size={size}
      aria-label={label}
      title={label}
      className={cn("aspect-square px-0", className)}
      {...props}
    >
      <Icon name={icon} size={14} />
    </Button>
  );
}
