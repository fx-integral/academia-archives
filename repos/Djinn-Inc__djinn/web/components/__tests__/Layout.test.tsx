import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Layout from "../Layout";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/"),
}));

// Mock next/image
vi.mock("next/image", () => ({
  default: (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    return <img {...props} />;
  },
}));

// Mock WalletButton
vi.mock("../WalletButton", () => ({
  default: () => <button>Mock Wallet</button>,
}));

// Mock TestnetFaucet
vi.mock("../TestnetFaucet", () => ({
  default: () => <button>Mock Faucet</button>,
}));

// Mock ReportError
vi.mock("../ReportError", () => ({
  default: () => null,
}));

// Mock useProtocolPaused — defaults to nothing paused; tests that exercise the
// maintenance banner override this via mockUseProtocolPaused.mockReturnValue().
const mockUseProtocolPaused = vi.fn(() => ({
  anyPaused: false,
  byContract: { escrow: false, collateral: false, creditLedger: false, account: false, signalCommitment: false, audit: false },
  loading: false,
}));
vi.mock("@/lib/hooks", () => ({
  useProtocolPaused: () => mockUseProtocolPaused(),
}));

beforeEach(() => {
  mockUseProtocolPaused.mockReturnValue({
    anyPaused: false,
    byContract: { escrow: false, collateral: false, creditLedger: false, account: false, signalCommitment: false, audit: false },
    loading: false,
  });
});

describe("Layout", () => {
  it("renders children in the main content area", () => {
    render(
      <Layout>
        <div data-testid="child">Test content</div>
      </Layout>,
    );
    expect(screen.getByTestId("child")).toBeTruthy();
    expect(screen.getByText("Test content")).toBeTruthy();
  });

  it("renders all navigation links", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    expect(screen.getByText("Home")).toBeTruthy();
    // Some labels appear in both nav and footer
    expect(screen.getAllByText("Genius").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Leaderboard").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("About").length).toBeGreaterThanOrEqual(1);
  });

  it("renders a skip link targeting main content", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip.getAttribute("href")).toBe("#main-content");
    const main = document.getElementById("main-content");
    expect(main).toBeTruthy();
  });

  it("renders the Djinn logo and brand name", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    // Brand name appears in header and footer
    const djinnElements = screen.getAllByText("Djinn");
    expect(djinnElements.length).toBeGreaterThanOrEqual(1);
  });

  it("renders the footer with copyright", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    const year = new Date().getFullYear();
    expect(screen.getByText(`\u00A9 ${year} Djinn Inc.`)).toBeTruthy();
  });

  it("toggles mobile menu on hamburger click", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    const toggle = screen.getByLabelText("Toggle menu");
    // Mobile menu not visible initially (nav links are in desktop nav only)
    // Click hamburger to open
    fireEvent.click(toggle);
    // Now mobile nav should render additional links
    // Click again to close
    fireEvent.click(toggle);
  });

  it("renders external links with proper attributes", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    const githubLinks = screen.getAllByLabelText("GitHub");
    for (const link of githubLinks) {
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
  });

  it("does not render maintenance banner when no contracts are paused", () => {
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders maintenance banner when any contract is paused", () => {
    mockUseProtocolPaused.mockReturnValue({
      anyPaused: true,
      byContract: { escrow: true, collateral: false, creditLedger: false, account: false, signalCommitment: false, audit: false },
      loading: false,
    });
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    const banner = screen.getByRole("alert");
    expect(banner.textContent).toContain("paused for maintenance");
    expect(banner.textContent).toContain("Escrow");
  });

  it("lists every paused contract in the banner", () => {
    mockUseProtocolPaused.mockReturnValue({
      anyPaused: true,
      byContract: { escrow: true, collateral: true, creditLedger: true, account: true, signalCommitment: true, audit: true },
      loading: false,
    });
    render(
      <Layout>
        <div>content</div>
      </Layout>,
    );
    const banner = screen.getByRole("alert");
    expect(banner.textContent).toContain("Escrow");
    expect(banner.textContent).toContain("Collateral");
    expect(banner.textContent).toContain("Credits");
    expect(banner.textContent).toContain("Account");
    expect(banner.textContent).toContain("Signals");
    expect(banner.textContent).toContain("Audit");
  });
});
