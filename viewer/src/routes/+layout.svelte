<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { confidenceFilter } from '$lib/stores/tree';
	import { reviewStats, refreshStats } from '$lib/stores/review';
	import { corpora, selectedCorpus, loadCorpora } from '$lib/stores/corpus';
	import NavTabs from '$lib/components/NavTabs.svelte';

	import { onMount } from 'svelte';

	let { children } = $props();

	let activePage = $derived<'upload' | 'tasks' | 'review'>(
		$page.url.pathname.startsWith('/upload')
			? 'upload'
			: $page.url.pathname.startsWith('/tasks')
				? 'tasks'
				: 'review'
	);

	onMount(() => {
		loadCorpora();
		refreshStats($selectedCorpus?.id ?? 'default');
	});

	// When selectedCorpus changes, refresh stats
	$effect(() => {
		const sc = $selectedCorpus;
		if (sc) {
			refreshStats(sc.id);
		}
	});

	function setFilter(band: 'all' | 'high' | 'medium' | 'low') {
		$confidenceFilter = band;
	}

	function handleCorpusChange(e: Event) {
		const select = e.target as HTMLSelectElement;
		const corpusId = select.value;
		const corpus = $corpora.find((c) => c.id === corpusId);
		if (corpus) {
			$selectedCorpus = corpus;
		}
	}
</script>

<div class="app-shell">
	<header class="header">
		<div class="header-left">
			<h1 class="app-title">FOLIO <span class="accent">Insights</span></h1>
			<div class="corpus-selector">
				<select
					value={$selectedCorpus?.id ?? ''}
					onchange={handleCorpusChange}
					aria-label="Corpus selector"
				>
					{#if $corpora.length === 0}
						<option value="">No corpora</option>
					{/if}
					{#each $corpora as corpus}
						<option value={corpus.id}>{corpus.name}</option>
					{/each}
				</select>
			</div>
			<NavTabs {activePage} />
		</div>
		{#if activePage === 'review'}
			<div class="header-center">
				<div class="confidence-tabs" role="tablist" aria-label="Confidence filter">
					<button
						role="tab"
						class="tab"
						class:active={$confidenceFilter === 'all'}
						aria-selected={$confidenceFilter === 'all'}
						onclick={() => setFilter('all')}
					>
						All {#if $reviewStats}({$reviewStats.total}){/if}
					</button>
					<button
						role="tab"
						class="tab tab-high"
						class:active={$confidenceFilter === 'high'}
						aria-selected={$confidenceFilter === 'high'}
						onclick={() => setFilter('high')}
					>
						High {#if $reviewStats}({$reviewStats.by_confidence.high}){/if}
					</button>
					<button
						role="tab"
						class="tab tab-medium"
						class:active={$confidenceFilter === 'medium'}
						aria-selected={$confidenceFilter === 'medium'}
						onclick={() => setFilter('medium')}
					>
						Medium {#if $reviewStats}({$reviewStats.by_confidence.medium}){/if}
					</button>
					<button
						role="tab"
						class="tab tab-low"
						class:active={$confidenceFilter === 'low'}
						aria-selected={$confidenceFilter === 'low'}
						onclick={() => setFilter('low')}
					>
						Low {#if $reviewStats}({$reviewStats.by_confidence.low}){/if}
					</button>
				</div>
			</div>
			<div class="header-right">
				{#if $reviewStats}
					<span class="review-progress"
						>{$reviewStats.approved}/{$reviewStats.total} units reviewed</span
					>
				{/if}
				<button class="settings-btn" aria-label="Settings">
					<svg
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
					>
						<circle cx="12" cy="12" r="3" />
						<path
							d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
						/>
					</svg>
				</button>
			</div>
		{:else}
			<div class="header-center"></div>
			<div class="header-right">
				<button class="settings-btn" aria-label="Settings">
					<svg
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
					>
						<circle cx="12" cy="12" r="3" />
						<path
							d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
						/>
					</svg>
				</button>
			</div>
		{/if}
	</header>
	<main class="main-content">
		{@render children()}
	</main>
</div>

<style>
	.app-shell {
		display: flex;
		flex-direction: column;
		height: 100vh;
		overflow: hidden;
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 48px;
		padding: 0 var(--lg);
		background: var(--surface);
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: var(--md);
		height: 100%;
	}

	.app-title {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.3px;
		white-space: nowrap;
	}

	.accent {
		color: var(--accent);
	}

	.corpus-selector select {
		font-size: 13px;
		padding: var(--xs) var(--sm);
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
	}

	.header-center {
		display: flex;
		align-items: center;
	}

	.confidence-tabs {
		display: flex;
		gap: var(--xs);
		height: 36px;
		align-items: center;
	}

	.tab {
		padding: var(--xs) var(--sm);
		font-size: 13px;
		color: var(--text-dim);
		border-bottom: 2px solid transparent;
		transition: color 150ms, border-color 150ms;
	}

	.tab:hover {
		color: var(--text);
	}

	.tab.active {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}

	.tab-high.active {
		color: var(--green);
		border-bottom-color: var(--green);
	}

	.tab-medium.active {
		color: var(--orange);
		border-bottom-color: var(--orange);
	}

	.tab-low.active {
		color: var(--red);
		border-bottom-color: var(--red);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--md);
	}

	.review-progress {
		font-size: 13px;
		color: var(--accent);
		white-space: nowrap;
	}

	.settings-btn {
		color: var(--text-dim);
		display: flex;
		align-items: center;
	}

	.settings-btn:hover {
		color: var(--text);
	}

	.main-content {
		flex: 1;
		overflow: hidden;
	}
</style>
