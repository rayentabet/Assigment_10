# Chatbot UI frontend: React/TypeScript built by Vite, served as static files.
#
# Two stages so the runtime image carries only the built assets and nginx,
# not node_modules or the toolchain.

FROM node:20-alpine AS build

WORKDIR /app

# Copy manifests first so `npm ci` is cached until the dependencies change,
# not on every source edit.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines env vars at build time, so the API origin the browser will
# call has to be known here rather than at container start. It points at the
# host-published port because the browser runs outside the compose network.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build


FROM nginx:alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
