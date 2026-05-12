import { describe, it, expect } from "vitest";
import { ScaleReader, hexToBytes } from "../scale";

describe("ScaleReader", () => {
  it("decodes u8", () => {
    const r = new ScaleReader(new Uint8Array([0x42]));
    expect(r.readU8()).toBe(0x42);
  });

  it("decodes u16 little-endian", () => {
    const r = new ScaleReader(new Uint8Array([0x39, 0x05]));
    expect(r.readU16()).toBe(0x0539);
  });

  it("decodes u32 little-endian", () => {
    const r = new ScaleReader(new Uint8Array([0x01, 0x02, 0x03, 0x04]));
    expect(r.readU32()).toBe(0x04030201);
  });

  it("decodes u64 little-endian", () => {
    const r = new ScaleReader(
      new Uint8Array([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]),
    );
    expect(r.readU64()).toBe(0x0100000000000001n);
  });

  it("decodes u128 little-endian", () => {
    const r = new ScaleReader(new Uint8Array(16));
    r.readU128(); // all zeros
    expect(r.remaining).toBe(0);
  });

  it("decodes bool", () => {
    const r = new ScaleReader(new Uint8Array([0x00, 0x01, 0xff]));
    expect(r.readBool()).toBe(false);
    expect(r.readBool()).toBe(true);
    expect(r.readBool()).toBe(true);
  });

  describe("compact integers", () => {
    it("single-byte mode (0-63)", () => {
      // value 42 => (42 << 2) | 0 = 168 = 0xa8
      const r = new ScaleReader(new Uint8Array([0xa8]));
      expect(r.readCompactNumber()).toBe(42);
    });

    it("two-byte mode (64-16383)", () => {
      // value 100 => (100 << 2) | 1 = 401 => LE bytes: 0x91, 0x01
      const r = new ScaleReader(new Uint8Array([0x91, 0x01]));
      expect(r.readCompactNumber()).toBe(100);
    });

    it("four-byte mode (16384-1073741823)", () => {
      // value 100000 => (100000 << 2) | 2 = 400002 => LE 4 bytes
      const v = (100000 << 2) | 2;
      const buf = new Uint8Array(4);
      buf[0] = v & 0xff;
      buf[1] = (v >> 8) & 0xff;
      buf[2] = (v >> 16) & 0xff;
      buf[3] = (v >> 24) & 0xff;
      const r = new ScaleReader(buf);
      expect(r.readCompactNumber()).toBe(100000);
    });

    it("big-integer mode", () => {
      // 9449726346 (from the test fixture) — needs 5 bytes
      // mode 3: first byte = ((5-4) << 2) | 3 = 7
      // then 5 LE bytes of 9449726346
      const val = 9449726346n;
      const buf = new Uint8Array(6); // 1 + 5
      buf[0] = ((5 - 4) << 2) | 3; // = 7
      for (let i = 0; i < 5; i++) {
        buf[1 + i] = Number((val >> BigInt(i * 8)) & 0xffn);
      }
      const r = new ScaleReader(buf);
      expect(r.readCompact()).toBe(9449726346n);
    });
  });

  it("decodes AccountId (32 bytes)", () => {
    const bytes = new Uint8Array(32);
    bytes[0] = 0x8a;
    bytes[31] = 0x33;
    const r = new ScaleReader(bytes);
    const id = r.readAccountId();
    expect(id.length).toBe(32);
    expect(id[0]).toBe(0x8a);
    expect(id[31]).toBe(0x33);
    expect(r.remaining).toBe(0);
  });

  it("decodes vec length", () => {
    // 14 => (14 << 2) | 0 = 56 = 0x38
    const r = new ScaleReader(new Uint8Array([0x38]));
    expect(r.readVecLength()).toBe(14);
  });
});

describe("hexToBytes", () => {
  it("converts hex string to Uint8Array", () => {
    const bytes = hexToBytes("deadbeef");
    expect(bytes).toEqual(new Uint8Array([0xde, 0xad, 0xbe, 0xef]));
  });

  it("strips 0x prefix", () => {
    const bytes = hexToBytes("0xabcd");
    expect(bytes).toEqual(new Uint8Array([0xab, 0xcd]));
  });
});
