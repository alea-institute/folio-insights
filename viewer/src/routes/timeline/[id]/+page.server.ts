// viewer/src/routes/timeline/[id]/+page.server.ts
// D-09 supersession-timeline surface — Gate 4 (QUALITY-04) measurement target.
//
// Pattern: ONE awaited fetch (critical) + two unawaited (streamed).

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch, setHeaders }) => {
	const timelineCore = await fetch(`/api/timeline/${params.id}/core`).then((r) => r.json());

	setHeaders({ 'cache-control': 'public, max-age=60, s-maxage=60' });

	return {
		timeline: timelineCore,
		events: fetch(`/api/timeline/${params.id}/events`).then((r) => r.json()),
		supersessionChain: fetch(`/api/timeline/${params.id}/supersession_chain`).then((r) =>
			r.json()
		)
	};
};
