FROM node:20-alpine

# Install pnpm via corepack (pin major to avoid rebuild surprises)
RUN corepack enable && corepack prepare pnpm@10 --activate

WORKDIR /app

# Install deps (cached layer)
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# Copy source (overridden by bind mount in dev)
COPY . .

EXPOSE 3000
