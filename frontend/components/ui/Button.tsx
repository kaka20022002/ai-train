"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { Loader2 } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Show a spinner and disable interaction. */
  loading?: boolean;
  /** Icon rendered before the label. */
  leftIcon?: ReactNode;
  /** Icon rendered after the label. */
  rightIcon?: ReactNode;
  /** Stretch to the full width of the container. */
  fullWidth?: boolean;
}

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "text-xs px-3 py-1.5 gap-1.5 rounded-lg",
  md: "text-sm px-4 py-2.5 gap-2 rounded-xl",
  lg: "text-base px-5 py-3 gap-2 rounded-xl",
};

const SPINNER_SIZE: Record<ButtonSize, number> = { sm: 13, md: 15, lg: 17 };

// Color tokens map to the CSS variables defined in globals.css.
const VARIANT_STYLES: Record<ButtonVariant, CSSProperties> = {
  primary:   { background: "var(--accent)", color: "#fff", border: "1px solid var(--accent)" },
  danger:    { background: "var(--danger)", color: "#fff", border: "1px solid var(--danger)" },
  success:   { background: "var(--success)", color: "#fff", border: "1px solid var(--success)" },
  secondary: { background: "var(--surface2)", color: "var(--text)", border: "1px solid var(--border)" },
  ghost:     { background: "transparent", color: "var(--text-muted)", border: "1px solid transparent" },
};

/**
 * Reusable button primitive aligned with the app's design tokens.
 *
 * @example
 * <Button onClick={save}>保存</Button>
 * <Button variant="secondary" leftIcon={<Plus size={14} />}>新增</Button>
 * <Button variant="danger" loading={deleting} fullWidth>删除</Button>
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    leftIcon,
    rightIcon,
    fullWidth = false,
    disabled,
    className = "",
    style,
    children,
    type = "button",
    ...rest
  },
  ref
) {
  const isDisabled = disabled || loading;

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      className={[
        "inline-flex items-center justify-center font-medium",
        "transition-[opacity,background-color] duration-150",
        "hover:opacity-90 active:opacity-80",
        "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:opacity-50",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-0",
        SIZE_CLASSES[size],
        fullWidth ? "w-full" : "",
        className,
      ].filter(Boolean).join(" ")}
      style={{ ...VARIANT_STYLES[variant], ...style }}
      {...rest}
    >
      {loading ? (
        <Loader2 size={SPINNER_SIZE[size]} className="animate-spin" />
      ) : (
        leftIcon
      )}
      {children}
      {!loading && rightIcon}
    </button>
  );
});
