import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Build del tablero para Odoo: el mismo panel del asistente, compilado dentro del módulo logistica_tablero
// (Odoo sirve sus archivos estáticos; la imagen de Odoo no tiene Node). Regenerar tras cambiar el tablero con
//   bash scripts/build_tablero_odoo.sh      (desde la raíz del repo; usa Docker y `npm ci`, como la imagen del agente)
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  base: '/logistica_tablero/static/app/',
  build: {
    outDir: path.resolve(__dirname, '../../../odoo/addons/logistica_tablero/static/app'),
    emptyOutDir: true,
    rollupOptions: { input: path.resolve(__dirname, 'tablero-odoo.html') },
  },
  server: {
    proxy: {
      '/logistica': { target: process.env.ODOO_URL_DEV ?? 'http://127.0.0.1:8069', changeOrigin: false },
    },
  },
})
