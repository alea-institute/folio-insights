// viewer/src/routes/polysemy/[id]/+page.server.ts
// D-09 polysemy-fork surface — Gate 4 (QUALITY-04) measurement target.
//
// Pattern: ONE awaited fetch (critical) + two unawaited (streamed).

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch, setHeaders }) => {
	const polysemyCore = await fetch(`/api/polysemy/${params.id}/core`).then((r) => r.json());

	setHeaders({ 'cache-control': 'public, max-age=60, s-maxage=60' });

	return {
		polysemy: polysemyCore,
		siblings: fetch(`/api/polysemy/${params.id}/siblings`).then((r) => r.json()),
		disambiguations: fetch(`/api/polysemy/${params.id}/disambiguations`).then((r) => r.json())
	};
};
