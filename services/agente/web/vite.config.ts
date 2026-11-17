import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo la API va por el proxy de Vite: mismo origen, sin CORS (igual que en producción,
// donde FastAPI sirve este build).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api': { target: process.env.AGENTE_API ?? 'http://127.0.0.1:8003', changeOrigin: false },
    },
  },
})
