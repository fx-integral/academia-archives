// Retryable handler cooldown
export const cooldown_in_s = process.env.CI_MODE === 'true' ? 1 : 10

// Retryable handler retry default
export const retry_times = process.env.CI_MODE === 'true' ? 1 : 2