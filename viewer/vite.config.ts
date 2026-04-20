import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 5173,
		proxy: {
			'/api': {
				// API dev port — must match uvicorn port from bootup config (9925).
				// Per user auto-memory rule `feedback_api-client-proxy.md`: client code
				// (viewer/src/lib/api/client.ts) keeps API_BASE = '' and routes through
				// this proxy. Never hardcode a localhost port in client code — only
				// the proxy target names the backend port, and it lives here.
				target: 'http://localhost:9925',
				changeOrigin: true,
			},
		},
	},
});
