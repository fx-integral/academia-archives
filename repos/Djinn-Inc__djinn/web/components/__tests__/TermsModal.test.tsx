import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import TermsModal from "../TermsModal";

describe("TermsModal", () => {
  it("applies dialog accessibility attributes", () => {
    render(<TermsModal open onAccept={vi.fn()} onDecline={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBe("tos-title");
    expect(screen.getByRole("heading", { name: "Terms of Service" }).id).toBe("tos-title");
  });

  it("closes on Escape key", () => {
    const onDecline = vi.fn();
    render(<TermsModal open onAccept={vi.fn()} onDecline={onDecline} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  it("traps focus within the modal on Tab", () => {
    render(<TermsModal open onAccept={vi.fn()} onDecline={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    const decline = screen.getByRole("button", { name: "Decline" });
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
      ),
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    first.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);

    last.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    expect(focusable.includes(decline)).toBe(true);
  });
});
