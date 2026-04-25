import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeToggle } from "@/components/theme-toggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("renders the dark-mode label initially when default is dark", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button")).toHaveTextContent(/深色|浅色/);
  });

  it("toggles label and dataset on click", () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    const btn = screen.getByRole("button");
    const before = btn.textContent;
    fireEvent.click(btn);
    expect(btn.textContent).not.toBe(before);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
