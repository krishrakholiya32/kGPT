import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// In dev, /api and /favicon.svg are proxied to the FastAPI backend on :8000 so
// the app can use same-origin paths exactly as it does in production (where the
// backend serves the built SPA).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
