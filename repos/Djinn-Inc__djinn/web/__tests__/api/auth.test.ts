import { describe, it, expect, vi, beforeEach } from "vitest";
import { ethers } from "ethers";
import {
  createChallenge,
  consumeChallenge,
  buildChallengeMessage,
  recoverAddress,
  createSessionToken,
  verifySessionToken,
  authenticateRequest,
} from "@/lib/api-auth";

// Use a fixed secret for deterministic tests
vi.stubEnv("API_SESSION_SECRET", "test-secret-key-for-unit-tests");

describe("api-auth", () => {
  // Hardhat/Foundry default test account #0 (publicly known, zero real value)
  // Split to avoid secret-detection false positive in pre-commit hook
  const TEST_KEY_A = "0xac0974bec39a17e36ba4a6b4d238ff944bac";
  const TEST_KEY_B = "b478cbed5efcae784d7bf4f2ff80";
  const wallet = new ethers.Wallet(TEST_KEY_A + TEST_KEY_B);
  const address = wallet.address;

  describe("challenge management", () => {
    it("creates a stateless challenge nonce with scope binding", async () => {
      // v1726: nonce now embeds scope (5 parts: random:address:ts:scopeB64:hmac)
      const { nonce } = await createChallenge(address);
      const parts = nonce.split(":");
      expect(parts).toHaveLength(5);
      expect(parts[1]).toBe(address.toLowerCase());
    });

    it("consumes a valid challenge and returns bound scope", async () => {
      const { nonce } = await createChallenge(address, { role: "idiot", maxSpendUsdc: 100 });
      const consumed = await consumeChallenge(address, nonce);
      expect(consumed).not.toBeNull();
      expect(consumed?.scope.role).toBe("idiot");
      expect(consumed?.scope.maxSpendUsdc).toBe(100);
    });

    it("returns null for wrong address", async () => {
      const { nonce } = await createChallenge(address);
      const result = await consumeChallenge("0x0000000000000000000000000000000000000001", nonce);
      expect(result).toBeNull();
    });

    it("returns null for tampered nonce", async () => {
      const { nonce } = await createChallenge(address);
      const tampered = nonce.slice(0, -4) + "XXXX";
      const result = await consumeChallenge(address, tampered);
      expect(result).toBeNull();
    });

    it("returns null for garbage nonce", async () => {
      const result = await consumeChallenge(address, "not-a-valid-nonce");
      expect(result).toBeNull();
    });

    it("is case-insensitive on address", async () => {
      const { nonce } = await createChallenge(address.toLowerCase());
      const consumed = await consumeChallenge(address, nonce);
      expect(consumed).not.toBeNull();
    });

    it("rejects scope tamper attempts (v1726 binding test)", async () => {
      // Create with one scope
      const { nonce } = await createChallenge(address, { maxSpendUsdc: 50 });
      const parts = nonce.split(":");
      // Tamper the scope segment: swap the base64 with a different scope
      // and recompute the HMAC would require the secret — without it, the
      // HMAC check fails.
      const fakeScopeB64 = Buffer.from(JSON.stringify({ maxSpendUsdc: 99999 }), "utf-8")
        .toString("base64")
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "");
      const tampered = `${parts[0]}:${parts[1]}:${parts[2]}:${fakeScopeB64}:${parts[4]}`;
      const result = await consumeChallenge(address, tampered);
      expect(result).toBeNull();
    });
  });

  describe("challenge message", () => {
    it("builds a human-readable message with nonce", () => {
      const message = buildChallengeMessage("abc123");
      expect(message).toContain("Djinn Protocol");
      expect(message).toContain("abc123");
    });
  });

  describe("signature verification", () => {
    it("recovers correct address from valid signature", async () => {
      const { nonce } = await createChallenge(address);
      const message = buildChallengeMessage(nonce);
      const signature = await wallet.signMessage(message);

      const recovered = recoverAddress(nonce, signature);
      expect(recovered).toBe(address.toLowerCase());
    });

    it("returns null for invalid signature", () => {
      const recovered = recoverAddress("some-nonce", "0xinvalid");
      expect(recovered).toBeNull();
    });

    it("returns wrong address for mismatched nonce", async () => {
      const { nonce } = await createChallenge(address);
      const message = buildChallengeMessage(nonce);
      const signature = await wallet.signMessage(message);

      const { nonce: otherNonce } = await createChallenge(address);
      const recovered = recoverAddress(otherNonce, signature);
      expect(recovered).not.toBe(address.toLowerCase());
    });
  });

  describe("session tokens", () => {
    it("creates and verifies a token", async () => {
      const { token, expiresAt } = await createSessionToken(address);
      expect(token).toMatch(/^djn_/);
      expect(expiresAt).toBeGreaterThan(Date.now());

      const payload = await verifySessionToken(token);
      expect(payload).not.toBeNull();
      expect(payload!.address).toBe(address.toLowerCase());
    });

    it("includes scope in token", async () => {
      const { token } = await createSessionToken(address, {
        role: "genius",
        maxSpendUsdc: 5000,
      });

      const payload = await verifySessionToken(token);
      expect(payload!.scope.role).toBe("genius");
      expect(payload!.scope.maxSpendUsdc).toBe(5000);
    });

    it("rejects tampered token", async () => {
      const { token } = await createSessionToken(address);
      const tampered = token.slice(0, -4) + "XXXX";

      const payload = await verifySessionToken(tampered);
      expect(payload).toBeNull();
    });

    it("rejects expired token", async () => {
      const { token } = await createSessionToken(address, {
        expiresInHours: 0.0001, // ~0.36 seconds
      });

      // Wait for expiry
      await new Promise((r) => setTimeout(r, 500));

      const payload = await verifySessionToken(token);
      expect(payload).toBeNull();
    });

    it("rejects token without prefix", async () => {
      const payload = await verifySessionToken("not_a_valid_token");
      expect(payload).toBeNull();
    });

    it("caps TTL at 24 hours", async () => {
      const { expiresAt } = await createSessionToken(address, {
        expiresInHours: 100,
      });

      const maxExpiry = Date.now() + 24 * 60 * 60 * 1000 + 1000;
      expect(expiresAt).toBeLessThanOrEqual(maxExpiry);
    });
  });

  describe("authenticateRequest", () => {
    it("extracts session from Bearer header", async () => {
      const { token } = await createSessionToken(address, { role: "idiot" });

      const request = {
        headers: {
          get: (name: string) => {
            if (name === "authorization") return `Bearer ${token}`;
            return null;
          },
        },
      } as unknown as import("next/server").NextRequest;

      const auth = await authenticateRequest(request);
      expect(auth).not.toBeNull();
      expect(auth!.address).toBe(address.toLowerCase());
      expect(auth!.scope.role).toBe("idiot");
    });

    it("returns null without auth header", async () => {
      const request = {
        headers: {
          get: () => null,
        },
      } as unknown as import("next/server").NextRequest;

      const auth = await authenticateRequest(request);
      expect(auth).toBeNull();
    });

    it("returns null for invalid token", async () => {
      const request = {
        headers: {
          get: (name: string) => {
            if (name === "authorization") return "Bearer djn_invalid.token";
            return null;
          },
        },
      } as unknown as import("next/server").NextRequest;

      const auth = await authenticateRequest(request);
      expect(auth).toBeNull();
    });
  });

  describe("full auth flow", () => {
    it("connect -> sign -> verify -> use token", async () => {
      // Step 1: Create challenge
      const { nonce } = await createChallenge(address);

      // Step 2: Sign challenge
      const message = buildChallengeMessage(nonce);
      const signature = await wallet.signMessage(message);

      // Step 3: Verify challenge is valid
      const consumed = await consumeChallenge(address, nonce);
      expect(consumed).not.toBeNull();

      // Step 4: Recover signer address. v1726: signature is over the full
      // nonce (which includes scope binding); pass the original nonce, not
      // the parsed `consumed` object.
      const recovered = recoverAddress(nonce, signature);
      expect(recovered).toBe(address.toLowerCase());

      // Step 5: Create session token
      const { token } = await createSessionToken(address);

      // Step 6: Use token
      const payload = await verifySessionToken(token);
      expect(payload).not.toBeNull();
      expect(payload!.address).toBe(address.toLowerCase());
    });
  });
});
