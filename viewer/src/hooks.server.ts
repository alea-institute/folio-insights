// viewer/src/hooks.server.ts
// SSR middleware — Gate 4 tuning step 2 (cache-control) for D-07.
//
// ANTI-PATTERN AVOIDANCE (RESEARCH.md line 464): we use `@polka/compression`
// (installed via viewer/package.json) NOT the standard `compression` package,
// which buffers the entire response and defeats SvelteKit streaming. Full
// @polka wiring requires a custom adapter-node server.js wrapper; for Phase 0
// Gate 4 measurement, we rely on cache-control alone and defer per-chunk
// compression to Plan 08 if the target is unreachable.

import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event, {
		// Gate 4 streaming: keep page chunks unmodified so @polka/compression
		// can flush per-chunk when wired in a custom server.
		transformPageChunk: ({ html }) => html
	});

	// Gate 4 tuning step 2: edge-cache HTML 60s on the three D-09 SSR
	// surfaces (second-hit becomes <10ms). Does NOT apply to /api/* or other
	// routes — those remain uncached.
	const path = event.url.pathname;
	if (/^\/(shards|polysemy|timeline)\//.test(path)) {
		response.headers.set('cache-control', 'public, max-age=60, s-maxage=60');
	}

	return response;
};
