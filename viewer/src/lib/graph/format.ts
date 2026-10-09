/**
 * Display helpers for the shard dependency graph (drain U10): IRI shortening, the IRI <-> route
 * parameter mapping, and the per-field edge vocabulary shared by the graph and its legend.
 */

const SHARD_URN = /^urn:folio:shard\/([0-9a-f]{32})$/;
const HEX32 = /^[0-9a-f]{32}$/;

/**
 * The route parameter for a shard IRI: the 32-hex body for a shard URN (a clean, stable URL:
 * `/shards/<hex>/graph`), else the whole IRI percent-encoded as one path segment.
 */
export function shardParam(iri: string): string {
	const m = SHARD_URN.exec(iri);
	return m ? m[1] : encodeURIComponent(iri);
}

/** Inverse of `shardParam` for an already-decoded route parameter. */
export function shardIriFromParam(param: string): string {
	return HEX32.test(param) ? `urn:folio:shard/${param}` : param;
}

/** The graph API's depth bounds (`api/routes/shard.py`). */
export const MAX_GRAPH_DEPTH = 8;
export const DEFAULT_GRAPH_DEPTH = 3;

/** A `?depth=` value clamped to 0..8, or the default for a missing or malformed value. */
export function parseDepth(raw: string | null): number {
	if (raw === null || !/^\d+$/.test(raw)) return DEFAULT_GRAPH_DEPTH;
	return Math.min(MAX_GRAPH_DEPTH, Number(raw));
}

/** The viewer URL of a shard's graph view. */
export function graphHref(iri: string, corpus: string, depth?: number): string {
	const query = new URLSearchParams({ corpus });
	if (depth !== undefined && depth !== DEFAULT_GRAPH_DEPTH) query.set('depth', String(depth));
	return `/shards/${shardParam(iri)}/graph?${query}`;
}

/**
 * A short form of an IRI for a node face: a shard URN keeps its scheme and the first and last
 * six hex digits (`urn:folio:shard/3fa2c1…09be7d`); any other IRI longer than `max` keeps its
 * head and tail around an ellipsis.
 */
export function shortIri(iri: string, max = 34): string {
	const m = SHARD_URN.exec(iri);
	if (m) return `urn:folio:shard/${m[1].slice(0, 6)}…${m[1].slice(-6)}`;
	if (iri.length <= max) return iri;
	const keep = max - 1;
	const head = Math.ceil(keep * 0.6);
	return `${iri.slice(0, head)}…${iri.slice(iri.length - (keep - head))}`;
}

/** Envelope dependency fields, as the API names them. */
export type EdgeField =
	| 'elaborates'
	| 'depends_on_axioms'
	| 'depends_on_definitions'
	| 'depends_on_precedents'
	| 'depends_on_shards';

export interface EdgeStyle {
	/** The vocabulary term (`fi:elaborates`, `fi:dependsOnAxiom`, ...). */
	term: string;
	/** Plain-language legend text. */
	legend: string;
	/** CSS class suffix: `edge-<kind>`. */
	kind: 'elaborates' | 'axiom' | 'other';
}

export const EDGE_STYLES: Record<EdgeField, EdgeStyle> = {
	elaborates: { term: 'fi:elaborates', legend: 'elaborates (Tractarian parent)', kind: 'elaborates' },
	depends_on_axioms: { term: 'fi:dependsOnAxiom', legend: 'depends on axiom', kind: 'axiom' },
	depends_on_definitions: {
		term: 'fi:dependsOnDefinition',
		legend: 'depends on definition',
		kind: 'other',
	},
	depends_on_precedents: {
		term: 'fi:dependsOnPrecedent',
		legend: 'depends on precedent',
		kind: 'other',
	},
	depends_on_shards: { term: 'fi:dependsOnShard', legend: 'depends on shard', kind: 'other' },
};

/** The style of an edge field; an unknown field renders as "other". */
export function edgeStyle(field: string): EdgeStyle {
	return (
		(EDGE_STYLES as Record<string, EdgeStyle>)[field] ?? {
			term: field,
			legend: field.replaceAll('_', ' '),
			kind: 'other',
		}
	);
}
