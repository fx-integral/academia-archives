/**
 * Minimal SCALE codec decoder for reading Bittensor chain data.
 *
 * Only implements the subset needed to decode NeuronInfoLite responses.
 * Not a general-purpose codec — just enough for metagraph discovery.
 */

export class ScaleReader {
  private offset = 0;
  constructor(private data: Uint8Array) {}

  get remaining(): number {
    return this.data.length - this.offset;
  }

  readU8(): number {
    return this.data[this.offset++];
  }

  readU16(): number {
    const v =
      this.data[this.offset] | (this.data[this.offset + 1] << 8);
    this.offset += 2;
    return v;
  }

  readU32(): number {
    const v =
      this.data[this.offset] |
      (this.data[this.offset + 1] << 8) |
      (this.data[this.offset + 2] << 16) |
      (this.data[this.offset + 3] << 24);
    this.offset += 4;
    return v >>> 0;
  }

  readU64(): bigint {
    const lo = BigInt(this.readU32());
    const hi = BigInt(this.readU32());
    return (hi << 32n) | lo;
  }

  readU128(): bigint {
    const lo = this.readU64();
    const hi = this.readU64();
    return (hi << 64n) | lo;
  }

  readBool(): boolean {
    return this.data[this.offset++] !== 0;
  }

  /** SCALE compact integer — returns bigint for safety with large values. */
  readCompact(): bigint {
    const first = this.data[this.offset];
    const mode = first & 0x03;

    if (mode === 0) {
      this.offset += 1;
      return BigInt(first >> 2);
    }
    if (mode === 1) {
      const v = this.data[this.offset] | (this.data[this.offset + 1] << 8);
      this.offset += 2;
      return BigInt(v >> 2);
    }
    if (mode === 2) {
      const v =
        this.data[this.offset] |
        (this.data[this.offset + 1] << 8) |
        (this.data[this.offset + 2] << 16) |
        (this.data[this.offset + 3] << 24);
      this.offset += 4;
      return BigInt(v >>> 2);
    }

    // mode === 3: big-integer
    const nBytes = (first >> 2) + 4;
    this.offset += 1;
    let val = 0n;
    for (let i = 0; i < nBytes; i++) {
      val |= BigInt(this.data[this.offset + i]) << BigInt(i * 8);
    }
    this.offset += nBytes;
    return val;
  }

  /** Read compact as number (safe for u16/u32 values). */
  readCompactNumber(): number {
    return Number(this.readCompact());
  }

  /** Read 32 raw bytes (AccountId / public key). */
  readAccountId(): Uint8Array {
    const id = this.data.slice(this.offset, this.offset + 32);
    this.offset += 32;
    return id;
  }

  /** SCALE Vec prefix — returns the number of elements. */
  readVecLength(): number {
    return this.readCompactNumber();
  }

  /** Skip N bytes. */
  skip(n: number): void {
    this.offset += n;
  }
}

/** Convert hex string (with or without 0x prefix) to Uint8Array. */
export function hexToBytes(hex: string): Uint8Array {
  const h = hex.startsWith("0x") ? hex.slice(2) : hex;
  const bytes = new Uint8Array(h.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(h.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}
