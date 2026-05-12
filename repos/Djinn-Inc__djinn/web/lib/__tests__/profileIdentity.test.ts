import { describe, expect, it } from "vitest";
import { profileIdentity, profileLabel } from "../profileIdentity";

describe("profileIdentity", () => {
  const a = "0x68fc6a8b3b8e0d4c6f9c2e1a4b3d5e6f7a8b9c0d";
  const b = "0x4986f2b3a4c5d6e7f8091a2b3c4d5e6f7a8b11d3";

  it("is deterministic for the same address", () => {
    expect(profileIdentity(a)).toEqual(profileIdentity(a));
  });

  it("produces different handles for different addresses", () => {
    expect(profileIdentity(a).handle).not.toEqual(profileIdentity(b).handle);
  });

  it("returns a 2-letter initials badge and a gradient style", () => {
    const id = profileIdentity(a);
    expect(id.initials).toMatch(/^[A-Z]{2}$/);
    expect(id.avatarStyle.background).toContain("linear-gradient");
    expect(id.bio.length).toBeGreaterThan(10);
  });
});

describe("profileLabel", () => {
  it("includes handle and truncated address", () => {
    expect(profileLabel("0x1234567890abcdef1234567890abcdef12345678")).toMatch(
      /^@[A-Za-z]+ \([0][x]1234\.\.\.5678\)$/,
    );
  });
});
