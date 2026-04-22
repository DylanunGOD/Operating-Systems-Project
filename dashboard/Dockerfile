# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./

RUN npm ci --only=production && \
    npm cache clean --force

COPY . .

RUN npm run build

# Runtime stage
FROM node:20-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./

EXPOSE 3000

CMD ["serve", "-s", "dist", "-l", "3000"]
