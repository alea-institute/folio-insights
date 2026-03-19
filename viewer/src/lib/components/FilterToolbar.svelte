<script lang="ts">
	import {
		unitTypeFilter,
		confidenceBandFilter,
		reviewStatusFilter,
		flagFilter,
	} from '$lib/stores/tasks';

	const typeOptions = [
		{ id: 'best_practice', label: 'Best Practices' },
		{ id: 'principle', label: 'Principles' },
		{ id: 'pitfall', label: 'Pitfalls' },
		{ id: 'procedural_rule', label: 'Rules' },
		{ id: 'citation', label: 'Citations' },
	];

	const confidenceOptions = [
		{ id: 'high', label: 'High' },
		{ id: 'medium', label: 'Medium' },
		{ id: 'low', label: 'Low' },
	];

	const statusOptions = [
		{ id: 'unreviewed', label: 'Unreviewed' },
		{ id: 'approved', label: 'Approved' },
		{ id: 'rejected', label: 'Rejected' },
	];

	const flagOptions = [
		{ id: 'contradictions', label: 'Contradictions' },
		{ id: 'orphans', label: 'Orphans' },
		{ id: 'jurisdiction', label: 'Jurisdiction' },
	];

	function toggleType(id: string) {
		unitTypeFilter.update((current) => {
			if (current.includes(id)) {
				return current.filter((t) => t !== id);
			}
			return [...current, id];
		});
	}

	function setConfidence(id: string) {
		confidenceBandFilter.update((current) => (current === id ? 'all' : id));
	}

	function setStatus(id: string) {
		reviewStatusFilter.update((current) => (current === id ? 'all' : id));
	}

	function toggleFlag(id: string) {
		flagFilter.update((current) => {
			if (current.includes(id)) {
				return current.filter((f) => f !== id);
			}
			return [...current, id];
		});
	}
</script>

<div class="filter-toolbar">
	<!-- Type filter -->
	<div class="filter-group" role="group" aria-label="Unit type filter">
		<span class="group-label">Type</span>
		{#each typeOptions as opt}
			<button
				class="chip"
				class:active={$unitTypeFilter.includes(opt.id)}
				role="checkbox"
				aria-checked={$unitTypeFilter.includes(opt.id)}
				onclick={() => toggleType(opt.id)}
			>
				{opt.label}
			</button>
		{/each}
	</div>

	<!-- Confidence filter -->
	<div class="filter-group" role="group" aria-label="Confidence band filter">
		<span class="group-label">Confidence</span>
		{#each confidenceOptions as opt}
			<button
				class="chip"
				class:active={$confidenceBandFilter === opt.id}
				role="checkbox"
				aria-checked={$confidenceBandFilter === opt.id}
				onclick={() => setConfidence(opt.id)}
			>
				{opt.label}
			</button>
		{/each}
	</div>

	<!-- Status filter -->
	<div class="filter-group" role="group" aria-label="Review status filter">
		<span class="group-label">Status</span>
		{#each statusOptions as opt}
			<button
				class="chip"
				class:active={$reviewStatusFilter === opt.id}
				role="checkbox"
				aria-checked={$reviewStatusFilter === opt.id}
				onclick={() => setStatus(opt.id)}
			>
				{opt.label}
			</button>
		{/each}
	</div>

	<!-- Flags filter -->
	<div class="filter-group" role="group" aria-label="Flag filter">
		<span class="group-label">Flags</span>
		{#each flagOptions as opt}
			<button
				class="chip"
				class:active={$flagFilter.includes(opt.id)}
				role="checkbox"
				aria-checked={$flagFilter.includes(opt.id)}
				onclick={() => toggleFlag(opt.id)}
			>
				{opt.label}
			</button>
		{/each}
	</div>
</div>

<style>
	.filter-toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sm);
		padding: var(--sm) var(--md);
		border-bottom: 1px solid var(--border);
		background: var(--surface);
		flex-shrink: 0;
		position: sticky;
		top: 0;
		z-index: 5;
	}

	.filter-group {
		display: flex;
		align-items: center;
		gap: var(--xs);
	}

	.group-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-dim);
		margin-right: var(--xs);
		flex-shrink: 0;
	}

	.chip {
		padding: var(--xs) var(--sm);
		border-radius: 9999px;
		font-size: 11px;
		color: var(--text-dim);
		background: var(--surface2);
		border: 1px solid transparent;
		transition: background 150ms, color 150ms, border-color 150ms;
		white-space: nowrap;
	}

	.chip:hover {
		color: var(--text);
	}

	.chip.active {
		background: var(--highlight);
		color: var(--accent);
		border-color: var(--accent-dim);
	}
</style>
