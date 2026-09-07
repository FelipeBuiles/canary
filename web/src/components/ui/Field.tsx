import {
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "../../lib/cn";

type FieldLabelProps = LabelHTMLAttributes<HTMLLabelElement>;

export function FieldLabel({ className, ...props }: FieldLabelProps) {
  return <label className={cn("ui-field-label", className)} {...props} />;
}

type TextFieldProps = InputHTMLAttributes<HTMLInputElement>;

export function TextField({ className, type = "text", ...props }: TextFieldProps) {
  return <input type={type} className={cn("ui-field", className)} {...props} />;
}

type SelectFieldProps = SelectHTMLAttributes<HTMLSelectElement>;

/** Native field semantics preserve form submission, validation and field events. */
export function SelectField({ className, ...props }: SelectFieldProps) {
  return <select className={cn("ui-field", className)} {...props} />;
}

type TextAreaFieldProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export function TextAreaField({ className, ...props }: TextAreaFieldProps) {
  return <textarea className={cn("ui-field min-h-[88px] resize-y", className)} {...props} />;
}

interface SwitchFieldProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
  className?: string;
}

export function SwitchField({
  checked,
  onCheckedChange,
  disabled,
  label,
  className,
}: SwitchFieldProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onCheckedChange(!checked)}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-11 w-[54px] cursor-pointer items-center border-[2px] border-ink-black transition-[background-color,opacity] duration-150 disabled:cursor-not-allowed disabled:opacity-55",
        checked ? "bg-hero-red" : "bg-bristol",
        className,
      )}
    >
      <span
        className={cn(
          "block h-5 w-5 border border-ink-black transition-transform duration-150",
          checked ? "translate-x-[27px] bg-bristol" : "translate-x-[3px] bg-ink-black",
        )}
      />
    </button>
  );
}
