# Development image only: runs the Vite dev server with hot reload
FROM node:22-alpine

WORKDIR /app

# Install dependencies first so this layer is cached until package*.json changes
COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host 0.0.0.0 makes Vite reachable from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
