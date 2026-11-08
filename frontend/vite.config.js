import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // During local integration, proxy /v1 to a running API Gateway / SAM local
    // by setting VITE_API_BASE_URL instead. This proxy is a convenience only.
  },
})
