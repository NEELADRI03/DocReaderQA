import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      // File events from a Windows bind mount don't reach the container; poll instead
      usePolling: true,
    },
  },
})
