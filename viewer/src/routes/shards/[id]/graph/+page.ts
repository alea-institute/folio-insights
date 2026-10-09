// viewer/src/routes/shards/[id]/graph/+page.ts
// Drain U10 (R14): a shard's dependency graph — its derivation chain(s) to the axiom kernel and
// its dependents, every node with its Tractarian path and IRI.
//
// Route: /shards/<id>/graph?corpus=<corpus>&depth=<0-8>
//   <id> is the 32-hex body of a shard URN (urn:folio:shard/<hex>) or a percent-encoded IRI
//   ($lib/graph/format: shardParam / shardIriFromParam). The corpus defaults to "default"; the
//   depth to the API's default (3).
// Client-side load (SPA mode, see +layout.ts); both reads are open GETs.
import type { PageLoad } from './$types';
import { fetchShardDerivation, fetchShardGraph } from '$lib/api/client';
import { parseDepth, shardIriFromParam } from '$lib/graph/format';

export const load: PageLoad = async ({ params, url }) => {
	const iri = shardIriFromParam(params.id);
	const corpus = url.searchParams.get('corpus')?.trim() || 'default';
	const depth = parseDepth(url.searchParams.get('depth'));
	const [graph, derivation] = await Promise.all([
		fetchShardGraph(corpus, iri, depth),
		fetchShardDerivation(corpus, iri),
	]);
	return { iri, corpus, depth, graph, derivation };
};
