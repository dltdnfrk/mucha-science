import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearRunScopedSessionKeys } from "./runProgressStages";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

beforeEach(() => {
  vi.stubGlobal("sessionStorage", new MemoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("clearRunScopedSessionKeys", () => {
  it("removes current-run automation state without touching another run", () => {
    sessionStorage.setItem("muchanipo:auto-answer:run-current:Q1", "answer");
    sessionStorage.setItem("muchanipo:auto-approve:run-current:evidence", "approved");
    sessionStorage.setItem("muchanipo:auto-answer:run-other:Q1", "other");
    sessionStorage.setItem("run:run-current:pending_session", "pending");

    clearRunScopedSessionKeys("run-current");

    expect(sessionStorage.getItem("muchanipo:auto-answer:run-current:Q1")).toBeNull();
    expect(sessionStorage.getItem("muchanipo:auto-approve:run-current:evidence")).toBeNull();
    expect(sessionStorage.getItem("muchanipo:auto-answer:run-other:Q1")).toBe("other");
    expect(sessionStorage.getItem("run:run-current:pending_session")).toBe("pending");
  });
});
