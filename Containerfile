# Rebalance — container for Aiven Runtime (also works with docker/podman)
FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production PORT=8080
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src ./src
COPY public ./public
COPY benchmarks ./benchmarks
EXPOSE 8080
# DATABASE_URL (Aiven for PostgreSQL) and optionally ANTHROPIC_API_KEY come from the environment
CMD ["node", "src/server.mjs"]
