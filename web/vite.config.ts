/// <reference types="vitest" />
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'
import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import posthog from '@posthog/rollup-plugin'

function quietSdkSourceMaps(): Plugin {
  return {
    name: 'quiet-sdk-test-sourcemaps',
    apply: (_config, { mode }) => mode === 'test',
    configResolved(config) {
      const warnOnce = config.logger.warnOnce.bind(config.logger)
      config.logger.warnOnce = (message, options) => {
        // This published SDK map refers to missing monorepo sources.
        if (/Sourcemap for "[^"]*\/node_modules\/posthog-js\/dist\/module\.no-external\.js" points to (?:a source file outside its package|missing source files)/.test(message)) return
        warnOnce(message, options)
      }
    },
  }
}

export default defineConfig(({ isSsrBuild }) => ({
  resolve: { alias: {
    '@lettering-engine': fileURLToPath(new URL('../novel_to_comic/src/novel_to_comic/lettering/engine.mjs', import.meta.url)),
    '@lettering-voices': fileURLToPath(new URL('../novel_to_comic/src/novel_to_comic/lettering/voices.json', import.meta.url)),
  } },
  plugins: [quietSdkSourceMaps(), react(), tailwindcss(), ...(!isSsrBuild && process.env.POSTHOG_API_KEY && process.env.POSTHOG_PROJECT_ID ? [posthog({
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
    reporters: process.env.GITHUB_ACTIONS === 'true' ? ['dot', 'github-actions'] : ['dot'],
    silent: 'passed-only',
    projects: [
      {
        extends: true,
        test: {
          name: 'ui',
          pool: 'vmThreads',
          exclude: [...configDefaults.exclude, 'src/__tests__/telemetryIdentity.test.ts'],
        },
      },
      {
        extends: true,
        test: {
          name: 'sdk-reloads',
          // Reloading the real SDK requires vi.resetModules() across page loads.
          pool: 'forks',
          include: ['src/__tests__/telemetryIdentity.test.ts'],
        },
      },
    ],
    setupFiles: ['./src/test/setup.ts'],
    environmentOptions: {
      jsdom: {
        url: 'http://localhost/',
      },
    },
  },
}))
