"use client";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/use-theme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      onClick={toggle}
      type="button"
      aria-label={isDark ? "切换到浅色模式" : "切换到深色模式"}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md border transition hover:opacity-80"
      style={{
        backgroundColor: "var(--app-surface-elevated)",
        borderColor: "var(--app-border-subtle)",
        color: isDark
          ? "var(--app-accent-text-light)"
          : "var(--app-accent)",
      }}
    >
      {isDark ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
    </button>
  );
}
