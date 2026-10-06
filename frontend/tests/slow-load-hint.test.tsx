import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SlowLoadHint } from "../src/components/SlowLoadHint";

describe("SlowLoadHint", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("stays hidden for a fast load and appears after the delay", () => {
    render(<SlowLoadHint delayMs={4000} />);
    expect(screen.queryByRole("status")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(3999);
    });
    expect(screen.queryByRole("status")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status").textContent).toMatch(/waking up the server/i);
  });

  it("never appears if unmounted before the delay", () => {
    const { unmount } = render(<SlowLoadHint delayMs={4000} />);
    unmount();
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });
});
