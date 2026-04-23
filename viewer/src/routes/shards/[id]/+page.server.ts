// viewer/src/routes/shards/[id]/+page.server.ts
// D-09 SSR prototype + Gate 4 (QUALITY-04) measurement target.
//
// Pattern (RESEARCH.md Pattern 3, PATTERNS.md lines 1063-1079):
//   - ONE awaited fetch on the critical path (must fit <200ms Gate 4 budget)
//   - Two unawaited fetches returned as promises — SvelteKit streams them
//     with {#await} blocks in +page.svelte
//   - Relative URLs only (feedback_api-client-proxy.md).
//
// setHeaders() is redundant with hooks.server.ts regex for clarity/safety.

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch, setHeaders }) => {
	// Critical path — awaited; blocks initial paint (Gate 4 P95 <200ms).
	const shardCore = await fetch(`/api/shard/${params.id}/core`).then((r) => r.json());

	// Gate 4 tuning step 2 — edge-cache HTML for 60s.
	setHeaders({ 'cache-control': 'public, max-age=60, s-maxage=60' });

	return {
		shard: shardCore,
		dependencies: fetch(`/api/shard/${params.id}/deps`).then((r) => r.json()),
		attestations: fetch(`/api/shard/${params.id}/attests`).then((r) => r.json())
	};
};
