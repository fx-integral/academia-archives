import "@testing-library/jest-dom/vitest";

// Required by lib/api-auth.ts which reads process.env at module load time.
// Must be set here (before any test imports) because vi.stubEnv in individual
// test files runs AFTER ES module imports are hoisted.
process.env.API_SESSION_SECRET ??= "test-secret-key-for-unit-tests";
