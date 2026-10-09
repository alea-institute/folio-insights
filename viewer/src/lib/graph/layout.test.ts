/**
 * The dependency-graph layout (drain U10): longest-path layering, barycentre ordering, no
 * overlapping boxes, determinism, cycle safety; plus the display helpers in ./format.
 */
import { describe, expect, it } from 'vitest';

import { DEFAULT_LAYOUT, layoutGraph, neighbourOf, overlaps, type GraphLayout } from './layout';
import {
	DEFAULT_GRAPH_DEPTH,
	edgeStyle,
	graphHref,
	parseDepth,
	shardIriFromParam,
	shardParam,
	shortIri,
} from './format';

const nodes = (...ids: string[]) => ids.map((id) => ({ id }));
/** `from` depends on `to`. */
const edge = (from: string, to: string) => ({ from, to });

function layerOf(layout: GraphLayout): Record<string, number> {
	return Object.fromEntries(layout.nodes.map((n) => [n.id, n.layer]));
}

function assertNoOverlaps(layout: GraphLayout) {
	for (let i = 0; i < layout.nodes.length; i++) {
		for (let j = i + 1; j < layout.nodes.length; j++) {
			expect(overlaps(layout.nodes[i], layout.nodes[j]), `${i} vs ${j}`).toBe(false);
		}
	}
}

/** A deterministic pseudo-random DAG: node i may depend on any j < i. */
function randomDag(n: number, seed: number) {
	let state = seed;
	const rand = () => {
		state = (state * 1103515245 + 12345) % 2147483648;
		return state / 2147483648;
	};
	const ids = Array.from({ length: n }, (_, i) => `n${i}`);
	const edges: Array<{ from: string; to: string }> = [];
	for (let i = 1; i < n; i++) {
		for (let j = 0; j < i; j++) if (rand() < 0.12) edges.push(edge(ids[i], ids[j]));
	}
	return { nodes: nodes(...ids), edges };
}

describe('layering', () => {
	it('puts the AE4 chain left to right: kernel, hypothesis, shard, dependent', () => {
		// API order: root S first, then H, D, K (breadth-first).
		const layout = layoutGraph(nodes('S', 'H', 'D', 'K'), [
			edge('S', 'H'),
			edge('H', 'K'),
			edge('D', 'S'),
		]);
		expect(layerOf(layout)).toEqual({ K: 0, H: 1, S: 2, D: 3 });
		expect(layout.layers).toEqual([['K'], ['H'], ['S'], ['D']]);
		const x = Object.fromEntries(layout.nodes.map((n) => [n.id, n.x]));
		expect(x.K).toBeLessThan(x.H);
		expect(x.H).toBeLessThan(x.S);
		expect(x.S).toBeLessThan(x.D);
	});

	it('uses the longest path, so every edge runs strictly rightward', () => {
		// A depends on K directly and through B -> C -> K: A sits after C, not next to K.
		const layout = layoutGraph(nodes('A', 'B', 'C', 'K'), [
			edge('A', 'K'),
			edge('A', 'B'),
			edge('B', 'C'),
			edge('C', 'K'),
		]);
		expect(layerOf(layout)).toEqual({ K: 0, C: 1, B: 2, A: 3 });
		for (const e of layout.edges) {
			expect(e.back).toBe(false);
			expect(e.start.x).toBeLessThan(e.end.x);
		}
	});

	it('places independent nodes in the first column', () => {
		const layout = layoutGraph(nodes('x', 'y', 'z'), []);
		expect(layout.layers).toEqual([['x', 'y', 'z']]);
	});

	it('handles an empty graph', () => {
		const layout = layoutGraph([], []);
		expect(layout).toMatchObject({ nodes: [], edges: [], layers: [], width: 0, height: 0 });
	});

	it('ignores self-edges, duplicates and edges to unknown nodes', () => {
		const layout = layoutGraph(nodes('a', 'b', 'a'), [
			edge('a', 'a'),
			edge('a', 'b'),
			edge('a', 'b'),
			edge('a', 'ghost'),
		]);
		expect(layout.nodes.map((n) => n.id)).toEqual(['a', 'b']);
		expect(layout.edges).toHaveLength(1);
		expect(layerOf(layout)).toEqual({ b: 0, a: 1 });
	});
});

describe('cycles', () => {
	it('terminates on a legacy cycle, flags the back edge and still places every node', () => {
		const layout = layoutGraph(nodes('a', 'b', 'c'), [edge('a', 'b'), edge('b', 'c'), edge('c', 'a')]);
		expect(layout.nodes).toHaveLength(3);
		expect(layout.edges.filter((e) => e.back)).toHaveLength(1);
		assertNoOverlaps(layout);
	});
});

describe('ordering and geometry', () => {
	it('never overlaps two node boxes, on many random DAGs', () => {
		for (let seed = 1; seed <= 25; seed++) {
			const g = randomDag(30, seed);
			const layout = layoutGraph(g.nodes, g.edges);
			expect(layout.nodes).toHaveLength(30);
			assertNoOverlaps(layout);
			// Every box sits inside the reported canvas.
			for (const n of layout.nodes) {
				expect(n.x).toBeGreaterThanOrEqual(0);
				expect(n.y).toBeGreaterThanOrEqual(0);
				expect(n.x + n.width).toBeLessThanOrEqual(layout.width);
				expect(n.y + n.height).toBeLessThanOrEqual(layout.height);
			}
			// Each column's rows are contiguous slots 0..k-1.
			for (const column of layout.layers) {
				const orders = column.map((id) => layout.nodes.find((n) => n.id === id)!.order);
				expect(orders).toEqual(column.map((_, i) => i));
			}
		}
	});

	it('is deterministic: the same input gives identical output', () => {
		const g = randomDag(40, 7);
		expect(layoutGraph(g.nodes, g.edges)).toEqual(layoutGraph(g.nodes, g.edges));
	});

	it('barycentre ordering removes avoidable crossings', () => {
		// Left column [k1, k2]; right column input order [b, a] with a->k1, b->k2: the input order
		// crosses once, the barycentre order (a, b) crosses zero times.
		const layout = layoutGraph(nodes('k1', 'k2', 'b', 'a'), [edge('a', 'k1'), edge('b', 'k2')]);
		expect(layout.layers).toEqual([
			['k1', 'k2'],
			['a', 'b'],
		]);
		expect(layout.crossings).toBe(0);
	});

	it('keeps the input order when nothing improves (stable ties)', () => {
		const layout = layoutGraph(nodes('k', 'x', 'y', 'z'), [
			edge('x', 'k'),
			edge('y', 'k'),
			edge('z', 'k'),
		]);
		expect(layout.layers[1]).toEqual(['x', 'y', 'z']);
	});

	it('spaces columns and rows by the configured pitch and centres short columns', () => {
		const opt = { nodeWidth: 100, nodeHeight: 40, layerGap: 50, nodeGap: 10, padding: 5 };
		const layout = layoutGraph(nodes('k', 'a', 'b'), [edge('a', 'k'), edge('b', 'k')], opt);
		const at = Object.fromEntries(layout.nodes.map((n) => [n.id, n]));
		expect(at.k.x).toBe(5);
		expect(at.a.x).toBe(5 + 150);
		expect(at.b.y - at.a.y).toBe(50);
		// The single-node column is centred against the two-node one.
		expect(at.k.y + at.k.height / 2).toBe((at.a.y + at.b.y + at.b.height) / 2);
		expect(layout.width).toBe(5 * 2 + 2 * 150 - 50);
		expect(layout.height).toBe(5 * 2 + 2 * 50 - 10);
	});

	it('routes each edge from the dependency’s right side to the dependent’s left side', () => {
		const layout = layoutGraph(nodes('s', 'k'), [edge('s', 'k')]);
		const [e] = layout.edges;
		const k = layout.nodes.find((n) => n.id === 'k')!;
		const s = layout.nodes.find((n) => n.id === 's')!;
		expect(e.start).toEqual({ x: k.x + k.width, y: k.y + k.height / 2 });
		expect(e.end).toEqual({ x: s.x, y: s.y + s.height / 2 });
		expect(e.path.startsWith(`M ${e.start.x} ${e.start.y} C`)).toBe(true);
		expect(e.path.endsWith(`${e.end.x} ${e.end.y}`)).toBe(true);
	});

	it('uses the default geometry when no options are given', () => {
		const layout = layoutGraph(nodes('a'), []);
		expect(layout.nodes[0]).toMatchObject({
			x: DEFAULT_LAYOUT.padding,
			width: DEFAULT_LAYOUT.nodeWidth,
			height: DEFAULT_LAYOUT.nodeHeight,
		});
	});
});

describe('long edges', () => {
	it('route through a virtual lane, clear of the real nodes in the columns they cross', () => {
		// S depends on H (one layer) and on K79 (two layers): K79 -> S crosses H's column.
		const layout = layoutGraph(nodes('S', 'H', 'K6', 'K79'), [
			edge('S', 'H'),
			edge('S', 'K79'),
			edge('H', 'K6'),
		]);
		expect(layerOf(layout)).toEqual({ K6: 0, K79: 0, H: 1, S: 2 });
		const long = layout.edges.find((e) => e.to === 'K79')!;
		const h = layout.nodes.find((n) => n.id === 'H')!;
		// The path runs straight across H's column at one y (the lane), outside H's box.
		const lane = /C [^C]*? (\d+(?:\.\d+)?) (\d+(?:\.\d+)?) L (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)/.exec(long.path);
		expect(lane).not.toBeNull();
		const [, x1, y1, x2, y2] = lane!.map(Number);
		expect(x1).toBe(h.x);
		expect(x2).toBe(h.x + h.width);
		expect(y1).toBe(y2);
		expect(y1 < h.y || y1 > h.y + h.height).toBe(true);
		// Real-node ordering ignores lanes: H is row 0 of its column.
		expect(layout.layers[1]).toEqual(['H']);
		expect(h.order).toBe(0);
	});

	it('keeps lanes and boxes apart on random DAGs with long edges', () => {
		for (let seed = 30; seed <= 40; seed++) {
			const g = randomDag(24, seed);
			const layout = layoutGraph(g.nodes, g.edges);
			assertNoOverlaps(layout);
			for (const e of layout.edges) {
				for (const m of e.path.matchAll(/L (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)/g)) {
					const x = Number(m[1]);
					const y = Number(m[2]);
					const hit = layout.nodes.find(
						(n) => n.x + n.width === x && y > n.y && y < n.y + n.height
					);
					expect(hit, `${e.from}>${e.to} lane at ${x},${y}`).toBeUndefined();
				}
			}
		}
	});
});

describe('keyboard neighbours', () => {
	const layout = layoutGraph(nodes('k', 'a', 'b', 'd'), [
		edge('a', 'k'),
		edge('b', 'k'),
		edge('d', 'b'),
	]);

	it('moves within a column and clamps at its ends', () => {
		expect(neighbourOf(layout, 'a', 'down')).toBe('b');
		expect(neighbourOf(layout, 'b', 'down')).toBe('b');
		expect(neighbourOf(layout, 'a', 'up')).toBe('a');
	});

	it('moves across columns to the nearest row and stays put at the edges', () => {
		expect(neighbourOf(layout, 'k', 'right')).toBe('a');
		expect(neighbourOf(layout, 'd', 'left')).toBe('a');
		expect(neighbourOf(layout, 'k', 'left')).toBe('k');
		expect(neighbourOf(layout, 'd', 'right')).toBe('d');
		expect(neighbourOf(layout, 'ghost', 'up')).toBe('ghost');
	});
});

describe('format helpers', () => {
	const URN = 'urn:folio:shard/0123456789abcdef0123456789abcdef';

	it('maps shard URNs to their hex body and back', () => {
		expect(shardParam(URN)).toBe('0123456789abcdef0123456789abcdef');
		expect(shardIriFromParam(shardParam(URN))).toBe(URN);
	});

	it('percent-encodes any other IRI as one segment and reads it back decoded', () => {
		const iri = 'https://example.org/shards/a b/c';
		const param = shardParam(iri);
		expect(param).not.toContain('/');
		expect(shardIriFromParam(decodeURIComponent(param))).toBe(iri);
	});

	it('shortens IRIs for node faces', () => {
		expect(shortIri(URN)).toBe('urn:folio:shard/012345…abcdef');
		expect(shortIri('https://x.org/a')).toBe('https://x.org/a');
		const long = shortIri('https://example.org/' + 'a'.repeat(80) + '/tail');
		expect(long.length).toBe(34);
		expect(long).toContain('…');
		expect(long.endsWith('/tail')).toBe(true);
	});

	it('parses and clamps the depth parameter', () => {
		expect(parseDepth(null)).toBe(DEFAULT_GRAPH_DEPTH);
		expect(parseDepth('5')).toBe(5);
		expect(parseDepth('0')).toBe(0);
		expect(parseDepth('99')).toBe(8);
		expect(parseDepth('-1')).toBe(DEFAULT_GRAPH_DEPTH);
		expect(parseDepth('two')).toBe(DEFAULT_GRAPH_DEPTH);
	});

	it('builds graph links that keep the corpus and a non-default depth', () => {
		expect(graphHref(URN, 'kernel-corpus')).toBe(
			'/shards/0123456789abcdef0123456789abcdef/graph?corpus=kernel-corpus'
		);
		expect(graphHref(URN, 'c', 5)).toBe('/shards/0123456789abcdef0123456789abcdef/graph?corpus=c&depth=5');
	});

	it('styles edges per field, with a fallback for unknown fields', () => {
		expect(edgeStyle('elaborates').kind).toBe('elaborates');
		expect(edgeStyle('depends_on_axioms')).toMatchObject({ kind: 'axiom', term: 'fi:dependsOnAxiom' });
		expect(edgeStyle('depends_on_precedents').kind).toBe('other');
		expect(edgeStyle('depends_on_shards').kind).toBe('other');
		expect(edgeStyle('future_field')).toMatchObject({ kind: 'other', legend: 'future field' });
	});
});
