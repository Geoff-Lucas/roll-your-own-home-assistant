import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      // dev-time only — in production the built static files are served
      // from the same FastAPI process that serves /api, so no proxy is needed.
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
