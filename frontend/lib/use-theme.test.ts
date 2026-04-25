import { describe, it, expect, beforeEach, vi } from "vitest";
import { readStoredTheme, applyTheme, resolveInitialTheme } from "./use-theme";

describe("readStoredTheme", () => {
  beforeEach(() => localStorage.clear());

  it("returns null when no value", () => {
    expect(readStoredTheme()).toBeNull();
  });

  it("returns 'dark' when stored", () => {
    localStorage.setItem("docqa.theme", "dark");
    expect(readStoredTheme()).toBe("dark");
  });

  it("returns 'light' when stored", () => {
    localStorage.setItem("docqa.theme", "light");
    expect(readStoredTheme()).toBe("light");
  });

  it("returns null on invalid value", () => {
    localStorage.setItem("docqa.theme", "blue");
    expect(readStoredTheme()).toBeNull();
  });
});

describe("applyTheme", () => {
  it("sets data-theme on document.documentElement", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("persists to localStorage", () => {
    applyTheme("dark");
    expect(localStorage.getItem("docqa.theme")).toBe("dark");
  });
});

describe("resolveInitialTheme", () => {
  beforeEach(() => localStorage.clear());

  it("uses stored value when present", () => {
    localStorage.setItem("docqa.theme", "light");
    expect(resolveInitialTheme()).toBe("light");
  });

  it("falls back to dark when no stored, no matchMedia", () => {
    // jsdom's matchMedia is undefined by default
    expect(resolveInitialTheme()).toBe("dark");
  });

  it("respects prefers-color-scheme: dark when no stored value", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("dark"),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(resolveInitialTheme()).toBe("dark");
    vi.unstubAllGlobals();
  });

  it("respects prefers-color-scheme: light when no stored value", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(resolveInitialTheme()).toBe("light");
    vi.unstubAllGlobals();
  });
});
