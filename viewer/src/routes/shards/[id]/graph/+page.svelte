<!--
	/shards/<id>/graph — a shard's dependency graph (drain U10, R12/R14).

	The canvas shows what the shard derives from (left, toward the axiom kernel) and what derives
	from it (right), every node with its Tractarian path and IRI. The side panel lists each
	derivation chain to a kernel maxim (hover or focus one to light it in the graph), the edge
	legend and the walk's bounds.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import type { PageData } from './$types';
	import type { ShardGraphNode } from '$lib/api/client';
	import DependencyGraph from '$lib/components/DependencyGraph.svelte';
	import {
		EDGE_STYLES,
		depthOptions,
		edgeStyle,
		graphHref,
		shardParam,
		shortIri,
		truncationNote,
		type EdgeField,
	} from '$lib/graph/format';

	let { data }: { data: PageData } = $props();

	let graph = $derived('error' in data.graph ? null : data.graph);
	let graphError = $derived('error' in data.graph ? data.graph : null);
	let derivation = $derived('error' in data.derivation ? null : data.derivation);
	let nodeOf = $derived(new Map((graph?.nodes ?? []).map((n) => [n.iri, n])));
	let root: ShardGraphNode | undefined = $derived(graph ? nodeOf.get(graph.root) : undefined);
	let pathOf = $derived(
		new Map((derivation?.nodes ?? []).map((n) => [n.iri, n.tractarian_path]))
	);
	let counts = $derived({
		upstream: graph?.nodes.filter((n) => n.direction === 'upstream').length ?? 0,
		downstream: graph?.nodes.filter((n) => n.direction === 'downstream').length ?? 0,
	});

	let activeChain: number | null = $state(null);
	let highlighted = $derived(
		activeChain !== null && derivation ? (derivation.derivedFromKernel[activeChain]?.path ?? []) : []
	);

	const LEGEND: EdgeField[] = ['elaborates', 'depends_on_axioms', 'depends_on_shards'];
	const DEPTHS = depthOptions();
	let note = $derived(graph ? truncationNote(graph) : null);

	function changeDepth(event: Event) {
		const depth = Number((event.currentTarget as HTMLSelectElement).value);
		goto(graphHref(data.iri, data.corpus, depth), { keepFocus: true, noScroll: true });
	}

	function changeCorpus(event: SubmitEvent) {
		event.preventDefault();
		const form = new FormData(event.currentTarget as HTMLFormElement);
		const corpus = String(form.get('corpus') ?? '').trim() || 'default';
		goto(graphHref(data.iri, corpus, data.depth));
	}

	function stepField(chainIndex: number, step: number): string {
		const chain = derivation?.derivedFromKernel[chainIndex];
		return chain?.edges[step]?.field ?? '';
	}
</script>

<svelte:head>
	<title>Graph {root?.tractarian_path ?? shortIri(data.iri)} — FOLIO Insights</title>
</svelte:head>

<div class="graph-page">
	<header class="masthead">
		<nav class="crumbs" aria-label="Breadcrumb">
			<a href="/shards/{shardParam(data.iri)}">Shard</a>
			<span aria-hidden="true">/</span>
			<span aria-current="page">Dependency graph</span>
		</nav>
		<div class="title-row">
			<h1>
				<span class="eyebrow">Tractarian path</span>
				<span class="big-path" class:kernel={root?.is_kernel}
					>{root?.tractarian_path ?? '—'}</span
				>
			</h1>
			<div class="identity">
				{#if root?.is_kernel}
					<span class="kernel-mark">Kernel maxim · {root.citation}</span>
				{/if}
				<p class="root-label" class:latin={root?.is_kernel}>{root?.label ?? ''}</p>
				<code class="full-iri">{data.iri}</code>
			</div>
			<div class="controls">
				<form class="corpus-form" onsubmit={changeCorpus}>
					<label for="graph-corpus">Corpus</label>
					<input id="graph-corpus" name="corpus" value={data.corpus} spellcheck="false" />
				</form>
				<label class="depth">
					<span>Depth</span>
					<select value={data.depth} onchange={changeDepth} aria-label="Hops shown each way">
						{#each DEPTHS as option (option.value)}
							<option value={option.value}>{option.label}</option>
						{/each}
					</select>
				</label>
			</div>
		</div>
	</header>

	{#if graphError}
		<section class="state error" role="alert">
			<h2>
				{graphError.status === 404
					? 'Nothing to draw'
					: graphError.status === 0
						? 'The API did not answer'
						: `The API refused (${graphError.status})`}
			</h2>
			<p>{graphError.error}</p>
			{#if graphError.status === 404}
				<p class="hint">
					Check the corpus name above; the graph reads the corpus storage, not the review
					output.
				</p>
			{/if}
		</section>
	{:else if graph}
		<div class="body">
			<section class="stage" aria-label="Graph">
				{#if note}
					<p class="banner" role="status">{note}</p>
				{/if}
				<div class="axis" aria-hidden="true">
					<span>← derives from · toward the kernel</span>
					<span>dependents →</span>
				</div>
				<DependencyGraph {graph} corpus={data.corpus} depth={data.depth} {highlighted} />
			</section>

			<aside class="panel" aria-label="Derivation">
				<h2>Derivation to the kernel</h2>
				{#if !derivation}
					<p class="muted">The derivation could not be read.</p>
				{:else if root?.is_kernel || derivation.derivedFromKernel.length === 0}
					<p class="muted">
						{root?.is_kernel
							? 'This shard is a kernel maxim: derivations end here.'
							: `No kernel maxim is reached within ${derivation.max_depth} hops.`}
					</p>
				{:else}
					<ol class="chains">
						{#each derivation.derivedFromKernel as chain, c (chain.kernel_iri)}
							<li>
								<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
								<article
									class="chain"
									class:active={activeChain === c}
									onmouseenter={() => (activeChain = c)}
									onmouseleave={() => (activeChain = null)}
									onfocusin={() => (activeChain = c)}
									onfocusout={() => (activeChain = null)}
									aria-label="Chain to {chain.citation}, {chain.depth} hop{chain.depth === 1
										? ''
										: 's'}"
								>
									<header>
										<span class="cite">{chain.citation}</span>
										<span class="hops">{chain.depth} hop{chain.depth === 1 ? '' : 's'}</span>
									</header>
									<p class="maxim">{nodeOf.get(chain.kernel_iri)?.label ?? ''}</p>
									<ol class="steps">
										{#each chain.path as iri, s (iri)}
											<li class:kernel-step={iri === chain.kernel_iri}>
												<a href={graphHref(iri, data.corpus, data.depth)}>
													<span class="step-path">{pathOf.get(iri) ?? '—'}</span>
													<span class="step-iri">{shortIri(iri)}</span>
												</a>
												{#if s < chain.path.length - 1}
													{@const style = edgeStyle(stepField(c, s))}
													<span class="via via-{style.kind}">{style.legend}</span>
												{/if}
											</li>
										{/each}
									</ol>
								</article>
							</li>
						{/each}
					</ol>
				{/if}

				{#if derivation?.truncated}
					<p class="muted small" role="status">
						{derivation.truncated_reasons?.includes('node_cap')
							? `The walk stopped after ${derivation.node_cap} shards, nearest first;`
							: `The walk stopped at ${derivation.max_depth} hops;`} chains through farther shards
						are not listed.
					</p>
				{/if}

				<h2>Reading the graph</h2>
				<ul class="legend">
					{#each LEGEND as field (field)}
						{@const style = EDGE_STYLES[field]}
						<li>
							<svg width="44" height="10" aria-hidden="true">
								<line x1="2" y1="5" x2="42" y2="5" class="swatch swatch-{style.kind}" />
							</svg>
							<span><code>{style.term}</code> {style.legend}</span>
						</li>
					{/each}
					<li>
						<span class="kernel-swatch" aria-hidden="true"></span>
						<span>Kernel maxim (regula iuris), with its citation</span>
					</li>
				</ul>
				<p class="muted small">
					Arrows point from a shard to what it derives from. Definitions and precedents share
					the dotted style. {counts.upstream} upstream, {counts.downstream} downstream within {graph.depth}
					hop{graph.depth === 1 ? '' : 's'}.
				</p>
			</aside>
		</div>
	{/if}
</div>

<style>
	.graph-page {
		/* Local font stacks only (no third-party font request): an old-style book serif for
		   paths and kernel Latin, a humanist sans for the interface, the platform monospace. */
		--font-display:
			'Iowan Old Style', 'Palatino Linotype', Palatino, 'Book Antiqua', 'URW Palladio L',
			'P052', Georgia, serif;
		--font-mono:
			ui-monospace, 'SFMono-Regular', 'Cascadia Mono', 'DejaVu Sans Mono', Menlo, Consolas,
			monospace;
		--font-ui: Optima, Candara, 'Noto Sans', 'Segoe UI', 'Helvetica Neue', sans-serif;
		--gilt: #e3c27a;
		--gilt-dim: rgba(227, 194, 122, 0.38);
		--kernel-bg: #1e1a12;
		height: 100%;
		display: flex;
		flex-direction: column;
		font-family: var(--font-ui);
		background:
			radial-gradient(70% 60% at 0% 0%, rgba(227, 194, 122, 0.06), transparent 60%),
			linear-gradient(180deg, var(--bg), #0c0e13);
		overflow: hidden;
	}

	.masthead {
		padding: var(--md) var(--lg) var(--md);
		border-bottom: 1px solid var(--border);
	}
	.crumbs {
		font-size: 12px;
		color: var(--text-dim);
		display: flex;
		gap: var(--sm);
		margin-bottom: var(--sm);
	}
	.crumbs a {
		color: var(--text-dim);
		text-decoration: none;
	}
	.crumbs a:hover {
		color: var(--text);
		text-decoration: underline;
	}
	.title-row {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: end;
		gap: var(--lg);
	}
	h1 {
		display: flex;
		flex-direction: column;
		line-height: 1;
		font-weight: 400;
	}
	.eyebrow {
		font-size: 10.5px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--text-dim);
		margin-bottom: 6px;
	}
	.big-path {
		font-family: var(--font-display);
		font-size: 44px;
		font-weight: 600;
		color: var(--accent);
		letter-spacing: -0.01em;
		font-variant-numeric: lining-nums tabular-nums;
	}
	.big-path.kernel {
		color: var(--gilt);
	}
	.identity {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.kernel-mark {
		font-family: var(--font-display);
		font-variant-caps: small-caps;
		letter-spacing: 0.08em;
		color: var(--gilt);
		font-size: 14px;
	}
	.root-label {
		font-size: 15px;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.root-label.latin {
		font-family: var(--font-display);
		font-style: italic;
	}
	.full-iri {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--text-dim);
		overflow-wrap: anywhere;
		user-select: all;
	}
	.controls {
		display: flex;
		gap: var(--md);
		align-items: end;
	}
	.corpus-form,
	.depth {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-dim);
	}
	.controls input,
	.controls select {
		font-family: var(--font-mono);
		font-size: 13px;
		letter-spacing: 0;
		text-transform: none;
		padding: 6px 10px;
		background: var(--surface2);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 6px;
		min-width: 9rem;
	}
	.controls input:focus-visible,
	.controls select:focus-visible {
		border-color: var(--accent);
	}

	.body {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr) 340px;
	}
	.stage {
		min-width: 0;
		min-height: 0;
		padding: var(--md) var(--lg);
		display: flex;
		flex-direction: column;
		gap: var(--sm);
		overflow: hidden;
	}
	.axis {
		display: flex;
		justify-content: space-between;
		font-size: 11px;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--text-dim);
	}
	.banner {
		font-size: 12.5px;
		padding: 6px 12px;
		border-radius: 6px;
		background: var(--orphan);
		color: var(--orange);
		border: 1px solid rgba(232, 165, 76, 0.3);
		align-self: flex-start;
	}

	.panel {
		border-left: 1px solid var(--border);
		background: linear-gradient(180deg, var(--surface), rgba(26, 29, 39, 0.75));
		padding: var(--md) var(--lg) var(--lg);
		overflow-y: auto;
	}
	.panel h2 {
		font-family: var(--font-display);
		font-weight: 600;
		font-size: 17px;
		margin: var(--sm) 0 var(--md);
		letter-spacing: 0.01em;
	}
	.panel h2:not(:first-child) {
		margin-top: var(--xl);
	}
	.chains,
	.steps,
	.legend {
		list-style: none;
	}
	.chains > li + li {
		margin-top: var(--md);
	}
	.chain {
		border: 1px solid var(--gilt-dim);
		border-radius: 10px;
		padding: 12px 14px;
		background: rgba(30, 26, 18, 0.6);
		transition:
			border-color 160ms,
			transform 160ms;
	}
	.chain.active {
		border-color: var(--gilt);
		transform: translateX(-3px);
	}
	.chain header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.cite {
		font-family: var(--font-display);
		font-variant-caps: small-caps;
		letter-spacing: 0.08em;
		font-size: 16px;
		font-weight: 600;
		color: var(--gilt);
	}
	.hops {
		font-size: 11px;
		color: var(--text-dim);
		letter-spacing: 0.06em;
	}
	.maxim {
		font-family: var(--font-display);
		font-style: italic;
		font-size: 14.5px;
		color: #f1e6cc;
		margin: 4px 0 10px;
	}
	.steps li {
		display: flex;
		flex-direction: column;
	}
	.steps a {
		display: flex;
		gap: 10px;
		align-items: baseline;
		padding: 4px 6px;
		margin: 0 -6px;
		border-radius: 5px;
		text-decoration: none;
		color: var(--text);
	}
	.steps a:hover,
	.steps a:focus-visible {
		background: var(--surface3);
	}
	.step-path {
		font-family: var(--font-mono);
		font-weight: 600;
		color: var(--accent);
		min-width: 3.5rem;
	}
	.kernel-step .step-path {
		color: var(--gilt);
	}
	.step-iri {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.via {
		font-size: 11px;
		padding: 2px 0 2px 1.1rem;
		margin-left: 0.4rem;
		border-left: 2px solid;
		color: var(--text-dim);
	}
	.via-elaborates {
		border-color: var(--cyan);
	}
	.via-axiom {
		border-color: var(--gilt);
		border-left-style: dashed;
	}
	.via-other {
		border-color: var(--purple);
		border-left-style: dotted;
	}

	.legend li {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 12.5px;
		color: var(--text);
		padding: 4px 0;
	}
	.legend code {
		font-family: var(--font-mono);
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.swatch {
		stroke-width: 2;
	}
	.swatch-elaborates {
		stroke: var(--cyan);
	}
	.swatch-axiom {
		stroke: var(--gilt);
		stroke-dasharray: 7 5;
	}
	.swatch-other {
		stroke: var(--purple);
		stroke-dasharray: 2 5;
		stroke-linecap: round;
	}
	.kernel-swatch {
		width: 44px;
		height: 16px;
		border: 1.5px solid var(--gilt);
		outline: 1px solid var(--gilt-dim);
		outline-offset: -4px;
		border-radius: 4px;
		background: var(--kernel-bg);
		flex-shrink: 0;
	}
	.muted {
		color: var(--text-dim);
		font-size: 13px;
	}
	.small {
		font-size: 12px;
		margin-top: var(--md);
		line-height: 1.55;
	}

	.state {
		margin: var(--2xl) auto;
		max-width: 34rem;
		padding: var(--lg);
		border: 1px solid var(--border);
		border-radius: 12px;
		background: var(--surface);
	}
	.state h2 {
		font-family: var(--font-display);
		font-size: 22px;
		margin-bottom: var(--sm);
	}
	.state p {
		color: var(--text-dim);
		overflow-wrap: anywhere;
	}
	.state .hint {
		margin-top: var(--sm);
		font-size: 12.5px;
	}

	@media (max-width: 960px) {
		.title-row {
			grid-template-columns: 1fr;
			align-items: start;
		}
		.body {
			grid-template-columns: 1fr;
			overflow-y: auto;
		}
		.panel {
			border-left: none;
			border-top: 1px solid var(--border);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.chain {
			transition: none;
		}
		.chain.active {
			transform: none;
		}
	}
</style>
