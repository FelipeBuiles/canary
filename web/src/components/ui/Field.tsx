import {
  Children,
  isValidElement,
  type ChangeEvent,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type OptionHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "../../lib/cn";
import { Select, type SelectOption } from "./Select";

type FieldLabelProps = LabelHTMLAttributes<HTMLLabelElement>;

export function FieldLabel({ className, ...props }: FieldLabelProps) {
  return <label className={cn("ui-field-label", className)} {...props} />;
}

type TextFieldProps = InputHTMLAttributes<HTMLInputElement>;

export function TextField({ className, type = "text", ...props }: TextFieldProps) {
  return <input type={type} className={cn("ui-field", className)} {...props} />;
}

type SelectFieldProps = SelectHTMLAttributes<HTMLSelectElement>;

/**
 * Drop-in replacement for the old native-select SelectField: accepts the same
 * <option> children and a ChangeEvent-style onChange, but renders the custom
 * print-shop Select so the system dropdown never clashes with the site.
 */
export function SelectField({
  className,
  children,
  value,
  onChange,
  disabled,
  id,
  "aria-label": ariaLabel,
}: SelectFieldProps) {
  const options: SelectOption[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement<OptionHTMLAttributes<HTMLOptionElement>>(child)) return;
    const optionValue = child.props.value ?? child.props.children;
    options.push({ value: String(optionValue ?? ""), label: String(child.props.children ?? "") });
  });

  return (
    <Select
      value={String(value ?? "")}
      options={options}
      disabled={disabled}
      id={id}
      aria-label={ariaLabel}
      onValueChange={(next) => {
        onChange?.({ target: { value: next } } as ChangeEvent<HTMLSelectElement>);
      }}
      className={cn("w-full", className)}
    />
  );
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
        "relative inline-flex h-8 w-[54px] cursor-pointer items-center border-[2px] border-ink-black transition-[background-color,opacity] duration-150 disabled:cursor-not-allowed disabled:opacity-55",
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
