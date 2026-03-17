<script lang="ts">
	let { variant = 'tree' }: { variant?: 'tree' | 'detail' | 'source' } = $props();

	const treeWidths = [180, 140, 200, 160, 120, 190];
</script>

<div class="skeleton skeleton-{variant}" aria-busy="true" aria-label="Loading">
	{#if variant === 'tree'}
		{#each treeWidths as w}
			<div class="pulse" style="width: {w}px; height: 28px;"></div>
		{/each}
	{:else if variant === 'detail'}
		<div class="pulse heading" style="width: 200px; height: 24px;"></div>
		{#each [1, 2, 3] as _}
			<div class="pulse card" style="width: 100%; height: 80px;"></div>
		{/each}
	{:else}
		{#each [100, 95, 100, 85, 90, 100, 75, 95] as pct}
			<div class="pulse" style="width: {pct}%; height: 16px;"></div>
		{/each}
	{/if}
</div>

<style>
	.skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
		padding: var(--md);
	}

	.pulse {
		background: var(--surface2);
		border-radius: 4px;
		animation: pulse 1.5s ease-in-out infinite;
	}

	.heading {
		margin-bottom: var(--sm);
	}

	.card {
		border-radius: 6px;
	}

	@keyframes pulse {
		0%, 100% { opacity: 0.4; }
		50% { opacity: 0.8; }
	}
</style>
