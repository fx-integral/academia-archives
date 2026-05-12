FROM node:20-alpine AS builder

WORKDIR /app

RUN npm install -g pnpm

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY . .

# Build the Next.js app. Several API routes (e.g. /api/auth/connect)
# read API_SESSION_SECRET / ADMIN_PASSWORD at module init and refuse to
# build when missing — `next build` evaluates dynamic API routes at
# compile time, so the placeholder is needed even though a real deploy
# injects them via the runtime env. The runtime env still overrides
# these values at container start.
ENV API_SESSION_SECRET=ci-placeholder-not-for-prod \
    ADMIN_PASSWORD=ci-placeholder-not-for-prod
RUN pnpm build

# --- Runtime stage ---
FROM node:20-alpine

WORKDIR /app

RUN npm install -g pnpm && apk add --no-cache curl

# Copy only the built app and production dependencies
COPY --from=builder /app/package.json /app/pnpm-lock.yaml* ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public

RUN adduser -D -h /app appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

CMD ["pnpm", "start"]
