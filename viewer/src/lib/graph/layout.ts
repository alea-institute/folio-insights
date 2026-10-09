/**
 * Layered left-to-right layout for a shard dependency graph (drain U10, R14).
 *
 * Pure and deterministic: the same input always gives the same coordinates, with no DOM, no
 * randomness and no dependency. The graph reads like a derivation: what a shard depends on sits
 * to its LEFT, so kernel maxims (which depend on nothing) form the first column and every edge
 * points rightward from a dependency to the shard that relies on it.
 *
 * Steps (a compact Sugiyama pass):
 *
 * 1. **Cycle breaking.** The dependency web should be acyclic (the U4 guard refuses new cycles),
 *    but a legacy cycle must never hang the view. A depth-first search in input order marks each
 *    edge that closes a cycle as a back edge; back edges are drawn but ignored for layering.
 * 2. **Longest-path layering.** `layer(n) = 0` for a node with no (forward) dependency in the
 *    graph, else `1 + max(layer(dependency))`, computed in topological order (Kahn). Every forward
 *    edge therefore runs from a lower layer to a strictly higher one.
 *    **Column compression.** A dense web can make the longest path as long as the node count
 *    (500 columns, ~170k px). Past `maxLayers` columns, layer `l` of `L` folds into column
 *    `floor(l * maxLayers / L)`: monotone, so no forward edge ever runs leftward; an edge whose
 *    ends fold into one column is drawn as a side arc, and each column keeps its nodes in layer
 *    order (a folded chain reads top to bottom, then continues in the next column).
 * 3. **Virtual lanes.** A forward edge spanning several columns gets one virtual node per
 *    intermediate column (a thin lane, not a box), so every segment spans one column, the
 *    ordering sees long edges, and they route through their lanes instead of under real nodes.
 *    At most `maxVirtual` lanes are made (edges in input order); an edge past the budget is
 *    drawn as one plain curve and left out of the ordering.
 * 4. **Barycentre ordering.** Each layer starts in input order (the API's breadth-first order),
 *    then alternating left-to-right and right-to-left sweeps reorder each layer by the mean
 *    position of its neighbours in the adjacent layer. Ties and neighbourless nodes keep their
 *    current place (a stable sort), so the result is deterministic. The best ordering seen (fewest
 *    crossings between adjacent layers, counted as inversions in O(E log V)) wins. Above
 *    `orderingLimit` segments the sweeps are skipped and the input order stands, so the work
 *    stays bounded on any input.
 * 5. **Coordinates.** Layer `l` is column `l`, `nodeWidth + layerGap` apart. Each column stacks
 *    its items top to bottom (boxes `nodeHeight` tall, lanes thinner) with `nodeGap` between
 *    them and is centred vertically against the tallest column, so no two boxes (or a box and a
 *    lane) can overlap.
 */

export interface LayoutNodeInput {
	id: string;
}

/** `from` depends on `to` (the API's edge direction): `to` is drawn left of `from`. */
export interface LayoutEdgeInput {
	from: string;
	to: string;
}

export interface LayoutOptions {
	nodeWidth: number;
	nodeHeight: number;
	/** Horizontal space between columns (edges are routed through it). */
	layerGap: number;
	/** Vertical space between nodes of one column. */
	nodeGap: number;
	/** Outer margin on every side. */
	padding: number;
	/** Barycentre sweep pairs (left-to-right then right-to-left). */
	sweeps: number;
	/** Most columns before the layering is compressed (see the module comment). */
	maxLayers: number;
	/** Most virtual lane nodes; long edges past the budget are drawn as plain curves. */
	maxVirtual: number;
	/** Most one-column segments (real and lane) the barycentre sweeps run on. */
	orderingLimit: number;
}

export const DEFAULT_LAYOUT: LayoutOptions = {
	nodeWidth: 248,
	nodeHeight: 92,
	layerGap: 96,
	nodeGap: 28,
	padding: 32,
	sweeps: 6,
	maxLayers: 24,
	maxVirtual: 600,
	orderingLimit: 6000,
};

export interface PositionedNode {
	id: string;
	layer: number;
	/** Row within the layer (0 = top). */
	order: number;
	/** Top-left corner. */
	x: number;
	y: number;
	width: number;
	height: number;
}

export interface RoutedEdge {
	from: string;
	to: string;
	/** True for an edge that closes a cycle (it runs right-to-left or within a column). */
	back: boolean;
	/** SVG path data, from the dependency's right side to the dependent's left side. */
	path: string;
	/** Anchor points: start (at the dependency `to`) and end (at the dependent `from`). */
	start: { x: number; y: number };
	end: { x: number; y: number };
}

export interface GraphLayout {
	nodes: PositionedNode[];
	edges: RoutedEdge[];
	/** Node ids per layer, top to bottom. */
	layers: string[][];
	width: number;
	height: number;
	/** Crossings between adjacent layers in the final ordering. */
	crossings: number;
	/** True when the longest path exceeded `maxLayers` and the columns were folded. */
	compressed: boolean;
}

interface Arc {
	/** Dependency (left). */
	u: number;
	/** Dependent (right). */
	v: number;
}

/** Edge `index` pairs that close a cycle, found by DFS from each node in input order. */
function backEdges(n: number, out: number[][], edgeIndex: Map<string, number[]>): Set<number> {
	const WHITE = 0;
	const GRAY = 1;
	const BLACK = 2;
	const color = new Array<number>(n).fill(WHITE);
	const back = new Set<number>();
	for (let start = 0; start < n; start++) {
		if (color[start] !== WHITE) continue;
		// Iterative DFS: stack of [node, next child index].
		const stack: Array<[number, number]> = [[start, 0]];
		color[start] = GRAY;
		while (stack.length > 0) {
			const top = stack[stack.length - 1];
			const [node, i] = top;
			if (i >= out[node].length) {
				color[node] = BLACK;
				stack.pop();
				continue;
			}
			top[1] = i + 1;
			const next = out[node][i];
			if (color[next] === GRAY) {
				for (const e of edgeIndex.get(`${node}>${next}`) ?? []) back.add(e);
			} else if (color[next] === WHITE) {
				color[next] = GRAY;
				stack.push([next, 0]);
			}
		}
	}
	return back;
}

/**
 * Number of crossings between two adjacent layers' arcs, given each node's row: the inversions of
 * the right-hand rows once the arcs are sorted by (left row, right row). Arcs sharing an endpoint
 * never count. O(E log E) (merge-sort inversion count).
 */
function crossingsBetween(arcs: Arc[], row: number[]): number {
	if (arcs.length < 2) return 0;
	const sorted = [...arcs].sort((a, b) => row[a.u] - row[b.u] || row[a.v] - row[b.v]);
	let values = sorted.map((a) => row[a.v]);
	let buffer = new Array<number>(values.length);
	let count = 0;
	for (let width = 1; width < values.length; width *= 2) {
		for (let lo = 0; lo < values.length; lo += 2 * width) {
			const mid = Math.min(lo + width, values.length);
			const hi = Math.min(lo + 2 * width, values.length);
			let i = lo;
			let j = mid;
			let k = lo;
			while (i < mid && j < hi) {
				if (values[j] < values[i]) {
					count += mid - i; // strictly smaller: every remaining left value crosses it
					buffer[k++] = values[j++];
				} else {
					buffer[k++] = values[i++];
				}
			}
			while (i < mid) buffer[k++] = values[i++];
			while (j < hi) buffer[k++] = values[j++];
		}
		[values, buffer] = [buffer, values];
	}
	return count;
}

function totalCrossings(layers: number[][], arcsBetween: Arc[][]): number {
	const row: number[] = [];
	for (const layer of layers) layer.forEach((node, i) => (row[node] = i));
	return arcsBetween.reduce((sum, arcs) => sum + crossingsBetween(arcs, row), 0);
}

/** Reorder `layer` by the barycentre of each node's neighbours in `fixed` (stable). */
function reorder(layer: number[], fixedRow: number[], neighbours: number[][]): number[] {
	const keyed = layer.map((node, index) => {
		const ns = neighbours[node];
		const key = ns.length === 0 ? index : ns.reduce((s, m) => s + fixedRow[m], 0) / ns.length;
		return { node, index, key };
	});
	keyed.sort((a, b) => a.key - b.key || a.index - b.index);
	return keyed.map((k) => k.node);
}

/** A horizontal-tangent cubic from the current point (sx, sy) to (ex, ey), as path data. */
function curve(sx: number, sy: number, ex: number, ey: number): string {
	const dx = Math.max(40, Math.abs(ex - sx) / 2);
	return ` C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`;
}

/**
 * Lay out `nodes` and `edges` left to right (see the module comment). Edges naming an unknown
 * node, self-edges and duplicate node ids are ignored (the first occurrence of an id wins).
 */
export function layoutGraph(
	nodes: readonly LayoutNodeInput[],
	edges: readonly LayoutEdgeInput[],
	options: Partial<LayoutOptions> = {}
): GraphLayout {
	const opt: LayoutOptions = { ...DEFAULT_LAYOUT, ...options };
	const ids: string[] = [];
	const index = new Map<string, number>();
	for (const node of nodes) {
		if (!index.has(node.id)) {
			index.set(node.id, ids.length);
			ids.push(node.id);
		}
	}
	const n = ids.length;

	// Arcs run dependency (u, left) -> dependent (v, right); keep input order, drop duplicates.
	const arcs: Arc[] = [];
	const kept: LayoutEdgeInput[] = [];
	const seen = new Set<string>();
	for (const edge of edges) {
		const v = index.get(edge.from);
		const u = index.get(edge.to);
		if (u === undefined || v === undefined || u === v) continue;
		const key = `${u}>${v}`;
		if (seen.has(key)) continue;
		seen.add(key);
		arcs.push({ u, v });
		kept.push(edge);
	}

	const out: number[][] = Array.from({ length: n }, () => []);
	const edgeIndex = new Map<string, number[]>();
	arcs.forEach((arc, i) => {
		out[arc.u].push(arc.v);
		const key = `${arc.u}>${arc.v}`;
		edgeIndex.set(key, [...(edgeIndex.get(key) ?? []), i]);
	});
	const back = backEdges(n, out, edgeIndex);

	// Longest-path layering over forward arcs (Kahn, ties in input order).
	const indegree = new Array<number>(n).fill(0);
	const forward: number[][] = Array.from({ length: n }, () => []);
	arcs.forEach((arc, i) => {
		if (back.has(i)) return;
		forward[arc.u].push(arc.v);
		indegree[arc.v]++;
	});
	const layerOf = new Array<number>(n).fill(0);
	const queue: number[] = [];
	for (let i = 0; i < n; i++) if (indegree[i] === 0) queue.push(i);
	for (let head = 0; head < queue.length; head++) {
		const u = queue[head];
		for (const v of forward[u]) {
			layerOf[v] = Math.max(layerOf[v], layerOf[u] + 1);
			if (--indegree[v] === 0) queue.push(v);
		}
	}

	const longest = layerOf.reduce((m, l) => Math.max(m, l), -1) + 1;
	const maxLayers = Math.max(1, Math.floor(opt.maxLayers));
	const compressed = longest > maxLayers;
	const column = compressed
		? layerOf.map((l) => Math.floor((l * maxLayers) / longest))
		: layerOf;
	const layerCount = n === 0 ? 0 : compressed ? maxLayers : longest;

	// Long forward arcs get one virtual node per intermediate column (within the lane budget), so
	// every segment spans one column: ordering then accounts for them and their edges route
	// around real nodes, not under. Arcs folded into one column join no column pair.
	const isVirtual: boolean[] = new Array<boolean>(n).fill(false);
	const nodeLayer: number[] = [...column];
	const left: number[][] = Array.from({ length: n }, () => []);
	const right: number[][] = Array.from({ length: n }, () => []);
	const arcsBetween: Arc[][] = Array.from({ length: Math.max(0, layerCount - 1) }, () => []);
	const chainOf: number[][] = arcs.map(() => []); // virtual nodes of each arc, left to right
	let laneBudget = Math.max(0, Math.floor(opt.maxVirtual));
	const link = (u: number, v: number) => {
		left[v].push(u);
		right[u].push(v);
		arcsBetween[nodeLayer[u]].push({ u, v });
	};
	arcs.forEach((arc, i) => {
		if (back.has(i)) return;
		const span = column[arc.v] - column[arc.u];
		if (span <= 0) return; // folded into one column: a side arc
		if (span > 1 && span - 1 > laneBudget) return; // past the lane budget: a plain curve
		let prev = arc.u;
		for (let l = column[arc.u] + 1; l < column[arc.v]; l++) {
			const dummy = isVirtual.length;
			isVirtual.push(true);
			nodeLayer.push(l);
			left.push([]);
			right.push([]);
			chainOf[i].push(dummy);
			link(prev, dummy);
			prev = dummy;
			laneBudget--;
		}
		link(prev, arc.v);
	});
	const total = isVirtual.length;

	let layers: number[][] = Array.from({ length: layerCount }, () => []);
	if (compressed) {
		// Inside a folded column, nodes start in layer order (input order within a layer).
		const byLayer = Array.from({ length: n }, (_, i) => i).sort(
			(a, b) => layerOf[a] - layerOf[b] || a - b
		);
		for (const i of byLayer) layers[nodeLayer[i]].push(i);
		for (let i = n; i < total; i++) layers[nodeLayer[i]].push(i);
	} else {
		for (let i = 0; i < total; i++) layers[nodeLayer[i]].push(i);
	}

	let best = layers.map((l) => [...l]);
	let bestCrossings = totalCrossings(best, arcsBetween);
	const row = new Array<number>(total).fill(0);
	const setRows = () => layers.forEach((l) => l.forEach((node, i) => (row[node] = i)));
	setRows();
	const segments = arcsBetween.reduce((sum, a) => sum + a.length, 0);
	// Folding needs the layer order inside each column (it keeps a folded chain top to bottom),
	// so the barycentre sweeps run only on an uncompressed layering.
	const sweeps = compressed || segments + total > opt.orderingLimit ? 0 : opt.sweeps;
	for (let sweep = 0; sweep < sweeps && bestCrossings > 0; sweep++) {
		for (let l = 1; l < layerCount; l++) {
			layers[l] = reorder(layers[l], row, left);
			layers[l].forEach((node, i) => (row[node] = i));
		}
		for (let l = layerCount - 2; l >= 0; l--) {
			layers[l] = reorder(layers[l], row, right);
			layers[l].forEach((node, i) => (row[node] = i));
		}
		const c = totalCrossings(layers, arcsBetween);
		if (c < bestCrossings) {
			bestCrossings = c;
			best = layers.map((l) => [...l]);
		}
	}
	layers = best;
	setRows();

	// Coordinates: each column stacks its items (real boxes, thin virtual lanes) top to bottom
	// and is centred against the tallest column.
	// Consecutive lanes pack tighter than boxes: a bundle of long edges stays a bundle.
	const laneHeight = Math.min(opt.nodeHeight, Math.max(8, opt.nodeGap / 2));
	const laneGap = Math.min(opt.nodeGap, 4);
	const itemHeight = (node: number) => (isVirtual[node] ? laneHeight : opt.nodeHeight);
	const gapAfter = (layer: number[], i: number) =>
		isVirtual[layer[i]] && isVirtual[layer[i + 1]] ? laneGap : opt.nodeGap;
	const columnHeight = (layer: number[]) => {
		let h = 0;
		for (let i = 0; i < layer.length; i++) {
			h += itemHeight(layer[i]) + (i + 1 < layer.length ? gapAfter(layer, i) : 0);
		}
		return h;
	};
	const tallest = layers.reduce((m, l) => Math.max(m, columnHeight(l)), 0);
	const colPitch = opt.nodeWidth + opt.layerGap;
	const top = new Array<number>(total).fill(0);
	const positioned: PositionedNode[] = new Array(n);
	layers.forEach((layer, l) => {
		let y = opt.padding + (tallest - columnHeight(layer)) / 2;
		let order = 0;
		layer.forEach((node, i) => {
			top[node] = y;
			if (!isVirtual[node]) {
				positioned[node] = {
					id: ids[node],
					layer: l,
					order: order++,
					x: opt.padding + l * colPitch,
					y,
					width: opt.nodeWidth,
					height: opt.nodeHeight,
				};
			}
			y += itemHeight(node) + (i + 1 < layer.length ? gapAfter(layer, i) : 0);
		});
	});

	const routed: RoutedEdge[] = arcs.map((arc, i) => {
		const dep = positioned[arc.u];
		const dependent = positioned[arc.v];
		const start = { x: dep.x + dep.width, y: dep.y + dep.height / 2 };
		const end = { x: dependent.x, y: dependent.y + dependent.height / 2 };
		let path = `M ${start.x} ${start.y}`;
		let at = start;
		for (const dummy of chainOf[i]) {
			const x = opt.padding + nodeLayer[dummy] * colPitch;
			const y = top[dummy] + laneHeight / 2;
			path += curve(at.x, at.y, x, y) + ` L ${x + opt.nodeWidth} ${y}`;
			at = { x: x + opt.nodeWidth, y };
		}
		if (!back.has(i) && dep.layer === dependent.layer) {
			// Folded into one column: leave the dependency's right side and re-enter the
			// dependent's right side, bulging into the gap beside the column.
			const sideEnd = { x: dependent.x + dependent.width, y: end.y };
			const bulge = Math.min(opt.layerGap * 0.8, 24 + Math.abs(sideEnd.y - start.y) / 6);
			path +=
				` C ${start.x + bulge} ${start.y}, ${sideEnd.x + bulge} ${sideEnd.y},` +
				` ${sideEnd.x} ${sideEnd.y}`;
			return { from: kept[i].from, to: kept[i].to, back: false, path, start, end: sideEnd };
		}
		path += curve(at.x, at.y, end.x, end.y);
		return { from: kept[i].from, to: kept[i].to, back: back.has(i), path, start, end };
	});

	const realLayers = layers.map((l) => l.filter((node) => !isVirtual[node]).map((node) => ids[node]));
	return {
		nodes: positioned,
		edges: routed,
		layers: realLayers,
		width: n === 0 ? 0 : 2 * opt.padding + layerCount * colPitch - opt.layerGap,
		height: n === 0 ? 0 : 2 * opt.padding + tallest,
		crossings: bestCrossings,
		compressed,
	};
}

/** True when two positioned boxes overlap (touching edges do not count). */
export function overlaps(a: PositionedNode, b: PositionedNode): boolean {
	return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/**
 * Keyboard neighbour of `id` in a layout: `up`/`down` move within its column, `left`/`right` to
 * the nearest row of the adjacent column (clamped). Returns `id` itself at an edge of the grid.
 */
export function neighbourOf(
	layout: GraphLayout,
	id: string,
	direction: 'up' | 'down' | 'left' | 'right'
): string {
	const node = layout.nodes.find((p) => p.id === id);
	if (!node) return id;
	const column = layout.layers[node.layer];
	if (direction === 'up') return column[Math.max(0, node.order - 1)];
	if (direction === 'down') return column[Math.min(column.length - 1, node.order + 1)];
	const target = node.layer + (direction === 'left' ? -1 : 1);
	const next = layout.layers[target];
	if (!next || next.length === 0) return id;
	// Nearest by vertical centre, ties to the upper node.
	const centre = node.y + node.height / 2;
	let best = next[0];
	let bestDistance = Infinity;
	for (const candidate of next) {
		const p = layout.nodes.find((q) => q.id === candidate)!;
		const d = Math.abs(p.y + p.height / 2 - centre);
		if (d < bestDistance) {
			best = candidate;
			bestDistance = d;
		}
	}
	return best;
}

const ARROWS: Record<string, 'up' | 'down' | 'left' | 'right'> = {
	ArrowUp: 'up',
	ArrowDown: 'down',
	ArrowLeft: 'left',
	ArrowRight: 'right',
};

/**
 * The node a key moves keyboard focus to from `id` (the graph's roving tabindex): arrows go to
 * `neighbourOf`, Home to the first node (top of the first column), End to the last (bottom of
 * the last column). `null` for any other key, so the caller leaves it alone (Enter opens the
 * focused node's link; Tab leaves the graph).
 */
export function keyTarget(layout: GraphLayout, id: string, key: string): string | null {
	const direction = ARROWS[key];
	if (direction) return neighbourOf(layout, id, direction);
	const columns = layout.layers.filter((column) => column.length > 0);
	if (columns.length === 0) return null;
	if (key === 'Home') return columns[0][0];
	if (key === 'End') {
		const last = columns[columns.length - 1];
		return last[last.length - 1];
	}
	return null;
}
