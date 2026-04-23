import adapter from '@sveltejs/adapter-node';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({
			out: 'build',
			// Use @polka/compression at runtime (Plan 00-07 wires hooks.server.ts).
			// Standard `compression` package breaks SvelteKit streaming per
			// svelte.dev/docs/kit/adapter-node — see RESEARCH.md Anti-pattern line 464.
			precompress: false,
			envPrefix: 'FOLIO_'
		}),
		paths: { base: '' }
	},
	vitePlugin: {
		dynamicCompileOptions: ({ filename }) =>
			filename.includes('node_modules') ? undefined : { runes: true }
	}
};

export default config;
