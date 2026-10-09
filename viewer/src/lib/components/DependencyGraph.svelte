<!--
	DependencyGraph — a shard's dependency web as a layered, left-to-right SVG (drain U10, R14).

	What a shard derives from sits to its left, so kernel maxims form the first column and the
	derived shards build rightward; arrows point from a shard to what it derives from (the RDF
	direction: S fi:elaborates H). Layout: $lib/graph/layout (longest-path layering + barycentre
	ordering, pure and deterministic).

	Every node is a link to its own graph view (click or Enter), shows its Tractarian path
	prominently and its truncated IRI; kernel maxims are set as inscriptions with their citation.
	Arrow keys move focus between nodes (up/down within a column, left/right across columns).
	A graph wider than the canvas is scaled to fit down to 62%, and scrolls beyond that.
	`highlighted` lights one derivation chain (the page's side panel drives it).
-->
<script lang="ts">
	import type { ShardGraph, ShardGraphNode } from '$lib/api/client';
	import { layoutGraph, neighbourOf, type GraphLayout } from '$lib/graph/layout';
	import { edgeStyle, graphHref, shortIri } from '$lib/graph/format';

	let {
		graph,
		corpus,
		depth,
		highlighted = [],
	}: {
		graph: ShardGraph;
		corpus: string;
		depth?: number;
		/** IRIs of one derivation chain to light (root first); empty lights nothing. */
		highlighted?: string[];
	} = $props();

	const NODE_W = 248;
	const NODE_H = 96;

	let layout: GraphLayout = $derived(
		layoutGraph(graph.nodes.map((n) => ({ id: n.iri })), graph.edges, {
			nodeWidth: NODE_W,
			nodeHeight: NODE_H,
		})
	);
	let byIri = $derived(new Map(graph.nodes.map((n) => [n.iri, n])));
	let fieldOf = $derived(new Map(graph.edges.map((e) => [`${e.from}>${e.to}`, e.field])));
	let lit = $derived(new Set(highlighted));
	let litEdges = $derived(
		new Set(highlighted.slice(1).map((iri, i) => `${highlighted[i]}>${iri}`))
	);

	let container: HTMLDivElement | undefined = $state();
	let canvasWidth = $state(0);
	/** Fit wide graphs to the canvas, but never below a readable 62%; beyond that it scrolls. */
	const MIN_SCALE = 0.62;
	let scale = $derived(
		layout.width > 0 && canvasWidth > 0
			? Math.max(MIN_SCALE, Math.min(1, (canvasWidth - 16) / layout.width))
			: 1
	);

	function describe(node: ShardGraphNode): string {
		const where =
			node.direction === 'root'
				? 'this shard'
				: `${node.direction === 'upstream' ? 'derives from' : 'dependent'}, ${node.distance} hop${node.distance === 1 ? '' : 's'}`;
		const kind = node.is_kernel
			? `kernel maxim ${node.citation}`
			: (node.shard_type ?? 'not in this corpus').replaceAll('_', ' ');
		const path = node.tractarian_path ? `path ${node.tractarian_path}` : 'no path';
		return `${path}; ${kind}; ${where}; ${node.label || node.iri}`;
	}

	function statusBadge(node: ShardGraphNode): string {
		if (!node.stored) return node.is_kernel ? 'not seeded' : 'not in corpus';
		return (node.epistemic_status ?? '').replaceAll('_', ' ');
	}

	const KEYS: Record<string, 'up' | 'down' | 'left' | 'right'> = {
		ArrowUp: 'up',
		ArrowDown: 'down',
		ArrowLeft: 'left',
		ArrowRight: 'right',
	};

	function onKeydown(event: KeyboardEvent) {
		const direction = KEYS[event.key];
		const target = (event.target as Element | null)?.closest?.('[data-node]');
		if (!direction || !target || !container) return;
		event.preventDefault();
		const next = neighbourOf(layout, target.getAttribute('data-node') ?? '', direction);
		const el = container.querySelector<SVGElement>(`[data-node="${CSS.escape(next)}"]`);
		el?.focus();
		el?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
	}
</script>

<!-- Arrow-key roving focus across the node links inside; each node is itself a link. -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
	class="canvas"
	bind:this={container}
	bind:clientWidth={canvasWidth}
	role="group"
	aria-label="Dependency graph: {graph.nodes.length} shards, {graph.edges.length} dependencies. Use arrow keys to move between shards and Enter to open one."
	onkeydown={onKeydown}
>
	<svg
		width={layout.width * scale}
		height={layout.height * scale}
		viewBox="0 0 {layout.width} {layout.height}"
		class:dimmed={lit.size > 0}
	>
		<defs>
			{#each ['elaborates', 'axiom', 'other'] as kind (kind)}
				<marker
					id="arrow-{kind}"
					viewBox="0 0 10 10"
					refX="10"
					refY="5"
					markerWidth="7"
					markerHeight="7"
					orient="auto-start-reverse"
				>
					<!-- Reversed at the path start, the tip (x=10) touches the dependency and the body trails
						along the edge, so the arrow reads "derives from" without hiding under the box. -->
					<path d="M 0 0 L 10 5 L 0 10 z" class="arrowhead arrowhead-{kind}" />
				</marker>
			{/each}
		</defs>

		<g class="edges" aria-hidden="true">
			{#each layout.edges as edge (edge.from + '>' + edge.to)}
				{@const field = fieldOf.get(`${edge.from}>${edge.to}`) ?? ''}
				{@const style = edgeStyle(field)}
				<path
					d={edge.path}
					class="edge edge-{style.kind}"
					class:back={edge.back}
					class:lit={litEdges.has(`${edge.from}>${edge.to}`)}
					marker-start="url(#arrow-{style.kind})"
				>
					<title>{shortIri(edge.from)} {style.term} {shortIri(edge.to)}</title>
				</path>
			{/each}
		</g>

		<g class="nodes">
			{#each layout.nodes as box (box.id)}
				{@const node = byIri.get(box.id)!}
				{@const navigable = node.stored || node.is_kernel}
				{#snippet face()}
					<rect class="frame" x={box.x} y={box.y} width={box.width} height={box.height} rx="10" />
					{#if node.is_kernel}
						<rect
							class="inscription"
							x={box.x + 4}
							y={box.y + 4}
							width={box.width - 8}
							height={box.height - 8}
							rx="7"
						/>
					{/if}
					<rect
						class="focus-ring"
						x={box.x - 4}
						y={box.y - 4}
						width={box.width + 8}
						height={box.height + 8}
						rx="13"
					/>
					<foreignObject x={box.x} y={box.y} width={box.width} height={box.height}>
						<div class="face" xmlns="http://www.w3.org/1999/xhtml">
							<div class="row">
								<span class="path" class:none={!node.tractarian_path}
									>{node.tractarian_path ?? '—'}</span
								>
								{#if node.is_kernel}
									<span class="citation">{node.citation}</span>
								{:else}
									<span class="status status-{node.epistemic_status ?? 'none'}"
										>{statusBadge(node)}</span
									>
								{/if}
							</div>
							<p class="label" class:latin={node.is_kernel}>
								{node.label || (node.stored ? '' : 'cited, but not stored in this corpus')}
							</p>
							<div class="iri">{shortIri(node.iri)}</div>
						</div>
					</foreignObject>
				{/snippet}
				{#if navigable}
					<a
						href={graphHref(node.iri, corpus, depth)}
						class="node"
						class:kernel={node.is_kernel}
						class:root={node.direction === 'root'}
						class:unstored={!node.stored}
						class:lit={lit.has(node.iri)}
						data-node={node.iri}
						style="--layer: {box.layer}"
						aria-label={describe(node)}
						aria-current={node.direction === 'root' ? 'page' : undefined}
					>
						{@render face()}
					</a>
				{:else}
					<g
						class="node unstored"
						class:lit={lit.has(node.iri)}
						data-node={node.iri}
						style="--layer: {box.layer}"
						tabindex="0"
						role="link"
						aria-disabled="true"
						aria-label="{describe(node)} (no graph: not stored in this corpus)"
					>
						{@render face()}
					</g>
				{/if}
			{/each}
		</g>
	</svg>
</div>

<style>
	.canvas {
		position: relative;
		overflow: auto;
		max-width: 100%;
		max-height: 100%;
		padding: var(--sm);
		border-radius: 14px;
		background:
			radial-gradient(circle at 1px 1px, rgba(228, 230, 240, 0.07) 1px, transparent 0) 0 0 / 22px
				22px,
			radial-gradient(120% 90% at 0% 50%, rgba(227, 194, 122, 0.07), transparent 55%),
			radial-gradient(90% 80% at 100% 0%, rgba(108, 140, 255, 0.08), transparent 60%),
			var(--bg);
		border: 1px solid var(--border);
	}

	svg {
		display: block;
		overflow: visible;
	}

	/* ── edges ─────────────────────────────────────────────── */
	.edge {
		fill: none;
		stroke-width: 1.75;
		opacity: 0.85;
		animation: edge-in 520ms ease-out backwards;
		animation-delay: 260ms;
		transition:
			opacity 180ms,
			stroke-width 180ms;
	}
	.edge-elaborates {
		stroke: var(--cyan);
	}
	.edge-axiom {
		stroke: var(--gilt);
		stroke-dasharray: 7 5;
	}
	.edge-other {
		stroke: var(--purple);
		stroke-dasharray: 2 5;
		stroke-linecap: round;
	}
	.edge.back {
		stroke: var(--red);
		stroke-dasharray: 3 3;
	}
	.arrowhead-elaborates {
		fill: var(--cyan);
	}
	.arrowhead-axiom {
		fill: var(--gilt);
	}
	.arrowhead-other {
		fill: var(--purple);
	}

	/* ── nodes ─────────────────────────────────────────────── */
	.node {
		cursor: pointer;
		outline: none;
		animation: node-in 420ms cubic-bezier(0.2, 0.7, 0.2, 1) backwards;
		animation-delay: calc(var(--layer) * 70ms);
	}
	.node.unstored {
		cursor: default;
	}
	.frame {
		fill: var(--surface);
		stroke: var(--border);
		stroke-width: 1.25;
		transition:
			stroke 160ms,
			fill 160ms;
	}
	.node:hover .frame {
		fill: var(--surface2);
		stroke: var(--accent-dim);
	}
	.node.root .frame {
		stroke: var(--accent);
		stroke-width: 2;
		filter: drop-shadow(0 0 10px rgba(108, 140, 255, 0.35));
	}
	.node.kernel .frame {
		fill: var(--kernel-bg);
		stroke: var(--gilt);
		stroke-width: 1.5;
	}
	.inscription {
		fill: none;
		stroke: var(--gilt-dim);
		stroke-width: 1;
	}
	.node.unstored .frame {
		stroke-dasharray: 5 4;
		fill: transparent;
	}
	.focus-ring {
		fill: none;
		stroke: var(--accent);
		stroke-width: 2;
		opacity: 0;
	}
	.node:focus-visible .focus-ring {
		opacity: 1;
	}

	.face {
		box-sizing: border-box;
		height: 100%;
		padding: 9px 12px 8px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		font-family: var(--font-ui);
		color: var(--text);
		pointer-events: none;
	}
	.row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
	}
	.path {
		font-family: var(--font-mono);
		font-size: 17px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--accent);
		font-variant-numeric: tabular-nums;
	}
	.path.none {
		color: var(--text-dim);
	}
	.kernel .path {
		color: var(--gilt);
	}
	.citation {
		font-family: var(--font-display);
		font-size: 13px;
		font-weight: 600;
		letter-spacing: 0.08em;
		color: var(--gilt);
		font-variant-caps: small-caps;
		white-space: nowrap;
	}
	.status {
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.09em;
		color: var(--text-dim);
		white-space: nowrap;
	}
	.status-hypothesis {
		color: var(--orange);
	}
	.label {
		font-size: 12.5px;
		line-height: 1.32;
		color: var(--text);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		flex: 1;
	}
	.label.latin {
		font-family: var(--font-display);
		font-style: italic;
		font-size: 14px;
		line-height: 1.25;
		color: #f1e6cc;
	}
	.iri {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-dim);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── highlight (one derivation chain) ─────────────────── */
	svg.dimmed .node:not(.lit) {
		opacity: 0.38;
	}
	svg.dimmed .edge:not(.lit) {
		opacity: 0.18;
	}
	.edge.lit {
		stroke-width: 3;
		opacity: 1;
	}
	.node.lit .frame {
		stroke-width: 2.25;
	}
	.node {
		transition: opacity 180ms;
	}

	@keyframes node-in {
		from {
			opacity: 0;
			transform: translateX(-10px);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@keyframes edge-in {
		from {
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.node,
		.edge {
			animation: none;
			transition: none;
		}
	}
</style>
