// viewer/src/routes/shards/[id]/+page.ts
// Phase 03.5: converted from +page.server.ts to a universal (client-side) load
// for SPA mode (adapter-static). The D-09 SSR prototype + Gate 4 (QUALITY-04)
// edge-cache `setHeaders` are dropped with the move off adapter-node; full SSR
// + the <200ms SSR budget are revisited for the Phase 20 GA cut.
// Streamed promises ({#await} in +page.svelte) work identically under client load.
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const shardCore = await fetch(`/api/shard/${params.id}/core`).then((r) => r.json());

	return {
		shard: shardCore,
		dependencies: fetch(`/api/shard/${params.id}/deps`).then((r) => r.json()),
		attestations: fetch(`/api/shard/${params.id}/attests`).then((r) => r.json())
	};
};
