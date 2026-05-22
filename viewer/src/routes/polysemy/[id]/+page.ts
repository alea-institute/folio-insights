// viewer/src/routes/polysemy/[id]/+page.ts
// Phase 03.5: converted from +page.server.ts to a universal (client-side) load
// for SPA mode (adapter-static). The D-09 SSR prototype + Gate 4 (QUALITY-04)
// edge-cache `setHeaders` are dropped with the move off adapter-node; full SSR
// + the <200ms SSR budget are revisited for the Phase 20 GA cut.
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const polysemyCore = await fetch(`/api/polysemy/${params.id}/core`).then((r) => r.json());

	return {
		polysemy: polysemyCore,
		siblings: fetch(`/api/polysemy/${params.id}/siblings`).then((r) => r.json()),
		disambiguations: fetch(`/api/polysemy/${params.id}/disambiguations`).then((r) => r.json())
	};
};
