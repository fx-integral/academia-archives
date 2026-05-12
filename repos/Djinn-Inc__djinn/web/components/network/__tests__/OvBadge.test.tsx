import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import OvBadge, { CANONICAL_OV } from "../OvBadge";

describe("OvBadge", () => {
  it("renders green check when registered on canonical contract", () => {
    const { container } = render(
      <OvBadge registered={true} contract={CANONICAL_OV} diagnosis={null} />,
    );
    const span = container.querySelector("span");
    expect(span?.className).toContain("emerald");
    expect(span?.textContent).toContain("\u2713");
    expect(span?.getAttribute("title")).toContain("Registered on canonical");
  });

  it("flags 'stale contract' when registered=true but contract is not canonical (UID 213 case)", () => {
    const { container } = render(
      <OvBadge
        registered={true}
        contract="0x4b140aA4BfB080337EE746f4Ec9e07ef660d80CF"
        diagnosis={null}
      />,
    );
    const span = container.querySelector("span");
    expect(span?.className).toContain("red");
    expect(span?.textContent).toBe("stale contract");
    expect(span?.getAttribute("title")).toContain("stale OV contract 0x4b140aA4");
  });

  it("flags 'stale env' on stale_env_override diagnosis (UID 1/86/189 case)", () => {
    const { container } = render(
      <OvBadge
        registered={false}
        contract="0x28b5738ff35E207E90b2974cbfae2BdC556acAf6"
        diagnosis="stale_env_override"
      />,
    );
    const span = container.querySelector("span");
    expect(span?.className).toContain("red");
    expect(span?.textContent).toBe("stale env");
  });

  it("flags 'missing' on missing_bootstrap diagnosis", () => {
    const { container } = render(
      <OvBadge registered={false} contract={CANONICAL_OV} diagnosis="missing_bootstrap" />,
    );
    const span = container.querySelector("span");
    expect(span?.className).toContain("red");
    expect(span?.textContent).toBe("missing");
  });

  it("falls back to 'off' when registered=false but diagnosis is absent", () => {
    const { container } = render(
      <OvBadge registered={false} contract={CANONICAL_OV} diagnosis={null} />,
    );
    const span = container.querySelector("span");
    expect(span?.textContent).toBe("off");
  });

  it("renders '-' when registered is null (old validator version)", () => {
    const { container } = render(<OvBadge registered={null} contract={null} diagnosis={null} />);
    expect(container.textContent).toBe("-");
  });

  it("renders '-' when registered is undefined (no /health field at all)", () => {
    const { container } = render(<OvBadge />);
    expect(container.textContent).toBe("-");
  });

  it("treats case-insensitive contract match (checksum vs lowercase)", () => {
    const checksummed = "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5";
    const { container } = render(
      <OvBadge registered={true} contract={checksummed} diagnosis={null} />,
    );
    const span = container.querySelector("span");
    expect(span?.className).toContain("emerald");
  });
});
