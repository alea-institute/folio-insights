<script lang="ts">
	let {
		status = 'ready',
		onclick,
	}: {
		status: 'ready' | 'disabled' | 'processing' | 'complete';
		onclick: () => void;
	} = $props();

	let label = $derived(
		status === 'processing'
			? 'Discovering...'
			: status === 'complete'
				? 'Tasks Discovered'
				: 'Discover Tasks'
	);

	let isDisabled = $derived(status === 'disabled' || status === 'processing');
</script>

{#if status === 'complete'}
	<a href="/tasks" class="discover-btn complete" data-sveltekit-preload-data>
		{label}
	</a>
{:else}
	<button
		class="discover-btn"
		class:processing={status === 'processing'}
		class:disabled-state={status === 'disabled'}
		disabled={isDisabled}
		{onclick}
	>
		{#if status === 'processing'}
			<span class="spinner"></span>
		{/if}
		{label}
	</button>
{/if}

<style>
	.discover-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--xs);
		height: 36px;
		padding: 0 var(--md);
		border-radius: 4px;
		font-size: 14px;
		font-weight: 600;
		background: var(--accent);
		color: #ffffff;
		border: none;
		cursor: pointer;
		text-decoration: none;
		transition: filter 150ms ease, opacity 150ms ease;
	}

	.discover-btn:hover:not(:disabled) {
		filter: brightness(0.9);
	}

	.discover-btn:active:not(:disabled) {
		transform: scale(0.98);
	}

	.discover-btn:disabled {
		cursor: not-allowed;
	}

	.discover-btn.disabled-state {
		background: var(--surface3);
		opacity: 0.5;
		cursor: not-allowed;
	}

	.discover-btn.processing {
		opacity: 0.8;
	}

	.discover-btn.complete {
		background: var(--green);
	}

	.spinner {
		display: inline-block;
		width: 14px;
		height: 14px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #fff;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
