import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeToggle } from "@/components/theme-toggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("renders an icon button with an accessible aria-label", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button").getAttribute("aria-label")).toMatch(
      /切换到(浅色|深色)模式/,
    );
  });

  it("toggles aria-label and dataset on click", () => {
    document.documentElement.dataset.theme = "light";
    render(<ThemeToggle />);
    const btn = screen.getByRole("button");
    const before = btn.getAttribute("aria-label");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-label")).not.toBe(before);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
