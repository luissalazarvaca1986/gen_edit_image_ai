import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En desarrollo (npm run dev) la API se proxea al backend publicado en el host
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8010' } },
});
