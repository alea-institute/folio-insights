import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

export default defineConfig({
	testDir: fileURLToPath(new URL('./tests/e2e', import.meta.url)),
	outputDir: join(process.env.RUNNER_TEMP || tmpdir(), 'folio-workbench-results'),
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: 0,
	use: {
		baseURL: 'http://127.0.0.1:4173',
		browserName: 'chromium',
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
	},
	projects: [
		{ name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
		{ name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
	],
	webServer: {
		command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
		cwd: fileURLToPath(new URL('.', import.meta.url)),
		url: 'http://127.0.0.1:4173',
		env: { FOLIO_WORKBENCH_FIXTURE: '1' },
		reuseExistingServer: false,
	},
});
