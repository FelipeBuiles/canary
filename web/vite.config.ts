/// <reference types="vitest" />
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  resolve: { alias: {
    '@lettering-engine': fileURLToPath(new URL('../novel_to_comic/src/novel_to_comic/lettering/engine.mjs', import.meta.url)),
    '@lettering-voices': fileURLToPath(new URL('../novel_to_comic/src/novel_to_comic/lettering/voices.json', import.meta.url)),
  } },
  plugins: [react(), tailwindcss()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          // Cache the shared framework and SDKs independently of app/translations.
          // Claim React first: Sentry's React integration must reuse this runtime.
          // Keep recursive dependency inclusion to avoid vendor → entry cycles.
          groups: [
            {
              name: 'app-runtime',
              test: /[\\/]node_modules[\\/](?:react|react-dom|scheduler|react-router|react-router-dom|@tanstack[\\/][^\\/]+)[\\/]/,
            },
            {
              name: 'supabase',
              test: /[\\/]node_modules[\\/]@supabase[\\/]/,
            },
            {
              name: 'sentry',
              test: /[\\/]node_modules[\\/](?:@sentry|@sentry-internal)[\\/]/,
            },
          ],
        },
      },
    },
  },
  server: {
    fs: { allow: ['..'] },
    proxy: {
      '/api': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    environmentOptions: {
      jsdom: {
        url: 'http://localhost/',
      },
    },
  },
})
