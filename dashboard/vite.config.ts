import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `npm run dev` proxies the hub so the dashboard works on http://localhost:5173 while the hub runs on :8000.
const hub = process.env.HIMAYA_HUB_URL ?? 'http://localhost:8000'
const proxied = ['/devices', '/events', '/api', '/rules', '/admin', '/enroll', '/snapshots', '/agents', '/health']

export default defineConfig({
  plugins: [react()],
  build: {
    // The hub serves its dashboard from hub/static, so a build lands there directly.
    outDir: '../hub/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,
  },
  server: {
    proxy: {
      ...Object.fromEntries(proxied.map((path) => [path, hub])),
      '/ws': { target: hub.replace(/^http/, 'ws'), ws: true },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
