import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReportErrorModal from "../ReportError";

const mockFetchFromAnyValidator = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/idiot",
}));

vi.mock("@/lib/api", () => ({
  fetchFromAnyValidator: (...args: unknown[]) => mockFetchFromAnyValidator(...args),
}));

describe("ReportErrorModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchFromAnyValidator.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  });

  it("submits feedback without diagnostics by default", async () => {
    render(<ReportErrorModal open onClose={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("What's on your mind?"), {
      target: { value: "The purchase table is confusing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(mockFetchFromAnyValidator).toHaveBeenCalledTimes(1));
    const [, init] = mockFetchFromAnyValidator.mock.calls[0];
    const payload = JSON.parse((init as RequestInit).body as string);

    expect(payload).toEqual({
      message: "The purchase table is confusing",
      url: "/idiot",
      source: "report-button",
    });
    expect(payload.userAgent).toBeUndefined();
    expect(payload.consoleErrors).toBeUndefined();
    expect(payload.errorMessage).toBeUndefined();
    expect(screen.queryByText(/No personal data is shared/i)).toBeNull();
  });

  it("only includes browser and console diagnostics after explicit opt-in", async () => {
    const error = new Error("wallet 0x1234567890abcdef failed");
    error.stack = "stack trace";
    console.error("recent failure 0x1234567890abcdef");

    render(<ReportErrorModal open onClose={vi.fn()} error={error} source="error-boundary" />);

    fireEvent.click(screen.getByRole("checkbox", { name: /Include diagnostic logs/i }));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(mockFetchFromAnyValidator).toHaveBeenCalledTimes(1));
    const [, init] = mockFetchFromAnyValidator.mock.calls[0];
    const payload = JSON.parse((init as RequestInit).body as string);

    expect(payload.message).toBe("User reported an error");
    expect(payload.url).toBe("/idiot");
    expect(payload.source).toBe("error-boundary");
    expect(payload.errorMessage).toBe("wallet 0x1234567890abcdef failed");
    expect(payload.errorStack).toBe("stack trace");
    expect(payload.userAgent).toBe(navigator.userAgent);
    expect(payload.consoleErrors).toContain("recent failure 0x1234567890abcdef");
  });
});
