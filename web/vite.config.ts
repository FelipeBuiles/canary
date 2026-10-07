/// <reference types="vitest" />
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import posthog from '@posthog/rollup-plugin'

export default defineConfig(({ isSsrBuild }) => ({
  resolve: { alias: {
    '@lettering-engine': fileURLToPath(new URL('../novel_to_comic/src/novel_to_comic/lettering/engine.mjs', import.meta.url)),
    '@lettering-voices': fileURLToPath(new URL('../novel_to_comic/src/novel_to_comic/lettering/voices.json', import.meta.url)),
  } },
  plugins: [react(), tailwindcss(), ...(!isSsrBuild && process.env.POSTHOG_API_KEY && process.env.POSTHOG_PROJECT_ID ? [posthog({
    personalApiKey: process.env.POSTHOG_API_KEY,
    projectId: process.env.POSTHOG_PROJECT_ID,
    host: process.env.POSTHOG_HOST,
    sourcemaps: { enabled: true, releaseName: 'canary-web', releaseVersion: process.env.VITE_CANARY_VERSION ?? 'dev', deleteAfterUpload: true },
  })] : [])],
  build: {
    manifest: !isSsrBuild,
    sourcemap: Boolean(process.env.POSTHOG_API_KEY && process.env.POSTHOG_PROJECT_ID),
    rolldownOptions: isSsrBuild ? {} : {
      output: {
        codeSplitting: {
          // Cache the shared framework and SDKs independently of app/translations.
          // Claim React first: The telemetry integration must reuse this runtime.
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
              name: 'posthog',
              test: /[\\/]node_modules[\\/](?:posthog-js|@posthog)[\\/]/,
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
}))
