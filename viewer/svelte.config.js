// Phase 03.5: reverted to adapter-static (SPA) — the v1.1 deploy model. FastAPI
// serves the static build/ at / via StaticFiles(html=True); /api is FastAPI too,
// single-origin, single Railway port. The v2.0 adapter-node SSR swap (commit
// f36f40c) was never deployed and required a node+proxy topology that didn't
// compose on Railway's single port. Full SSR returns for the Phase 20 GA cut.
import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({ fallback: 'index.html' }),
		paths: { base: '' },
		// Gate 5 (reproducible images): SvelteKit's default version name is
		// Date.now(), which lands in version.json and changes every chunk hash.
		// Pin it to SOURCE_DATE_EPOCH (the commit time) when the build sets it.
		version: { name: process.env.SOURCE_DATE_EPOCH || Date.now().toString() }
	},
	vitePlugin: {
		dynamicCompileOptions: ({ filename }) =>
			filename.includes('node_modules') ? undefined : { runes: true }
	}
};

export default config;
