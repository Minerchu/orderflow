# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 - build the Vue 3 / Vite bundle
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

# Build. VITE_* values are compiled in at build time, so pass the API base
# here if the frontend will be served from a different origin than the API.
# Left empty => the app calls the same origin at "/api", which is what the
# bundled Nginx reverse proxy expects.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 - serve static assets with Nginx and proxy /api to the backend
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Our own server block: SPA history fallback + /api reverse proxy.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/orderflow.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
