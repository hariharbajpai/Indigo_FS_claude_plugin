import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run build` writes the dashboard into the plugin (backend/fsa/web), where the Python server serves it.
// `npm run dev` proxies /api to a local server started with: python3 -m backend.fsa serve --port 4810
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../backend/fsa/web', emptyOutDir: true },
  server: { proxy: { '/api': 'http://localhost:4810' } },
  test: { environment: 'jsdom' },
})
