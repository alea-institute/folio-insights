<script lang="ts">
	import { confidenceFilter } from '$lib/stores/tree';
	import { reviewStats } from '$lib/stores/review';

	function setFilter(band: 'all' | 'high' | 'medium' | 'low') {
		$confidenceFilter = band;
	}
</script>

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

<style>
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
</style>
