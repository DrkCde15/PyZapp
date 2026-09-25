FROM node:22-slim

ENV NODE_ENV=production \
    SESSION_DIR=/app/sessions
WORKDIR /app

COPY package.json package-lock.json ./
# git is needed only at build time: Baileys pulls libsignal-node from GitHub.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && npm ci --omit=dev \
 && npm cache clean --force \
 && apt-get purge -y --auto-remove git \
 && rm -rf /var/lib/apt/lists/*

COPY src/ ./src/

RUN mkdir -p /app/sessions && chown -R node:node /app
USER node

VOLUME ["/app/sessions"]
EXPOSE 3001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://localhost:3001/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "src/server.js"]
