// viewer/src/routes/timeline/[id]/+page.ts
// Phase 03.5: converted from +page.server.ts to a universal (client-side) load
// for SPA mode (adapter-static). The D-09 SSR prototype + Gate 4 (QUALITY-04)
// edge-cache `setHeaders` are dropped with the move off adapter-node; full SSR
// + the <200ms SSR budget are revisited for the Phase 20 GA cut.
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const timelineCore = await fetch(`/api/timeline/${params.id}/core`).then((r) => r.json());

	return {
		timeline: timelineCore,
		events: fetch(`/api/timeline/${params.id}/events`).then((r) => r.json()),
		supersessionChain: fetch(`/api/timeline/${params.id}/supersession_chain`).then((r) =>
			r.json()
		)
	};
};
