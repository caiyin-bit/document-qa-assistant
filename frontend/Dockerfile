FROM node:20-alpine

# Use Chinese npm mirror to avoid timeouts on cn networks.
RUN npm config set registry https://registry.npmmirror.com

# Install pnpm via corepack (pin major to avoid rebuild surprises)
RUN corepack enable && corepack prepare pnpm@10 --activate

WORKDIR /app

# Install deps (cached layer); also point pnpm at the cn mirror.
COPY package.json pnpm-lock.yaml* ./
RUN pnpm config set registry https://registry.npmmirror.com && \
    pnpm install --frozen-lockfile

# Copy source (overridden by bind mount in dev)
COPY . .

EXPOSE 3000
