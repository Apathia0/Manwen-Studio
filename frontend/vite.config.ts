import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.VITE_BACKEND_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: backendTarget,
        timeout: 0,
      },
      '/static': backendTarget,
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/')) {
            return 'vendor-react';
          }
          if (id.includes('node_modules/lucide-react/')) {
            return 'vendor-lucide';
          }
          if (id.includes('node_modules/jszip/') || id.includes('node_modules/file-saver/') || id.includes('node_modules/qrcode/')) {
            return 'vendor-utils';
          }
        },
      },
    },
  },
})
