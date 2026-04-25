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
      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider transition"
      style={{
        backgroundColor: "var(--app-surface-elevated)",
        borderColor: "var(--app-border-subtle)",
        color: isDark
          ? "var(--app-accent-text-light)"
          : "var(--app-accent)",
      }}
    >
      {isDark ? <Moon className="h-3 w-3" /> : <Sun className="h-3 w-3" />}
      {isDark ? "深色 · DARK" : "浅色 · LIGHT"}
    </button>
  );
}
