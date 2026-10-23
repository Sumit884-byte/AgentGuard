import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Built into web/ui/dist and served by web/server.py; relative asset paths so any host path works.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // `npm run dev` talks to `python web/server.py` on :8000.
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
})
