<script lang="ts">
	let {
		onclick,
		disabled = false,
		status = 'idle',
	}: {
		onclick: () => void;
		disabled?: boolean;
		status?: 'idle' | 'processing' | 'complete' | 'error';
	} = $props();

	let label = $derived(
		status === 'processing'
			? 'Processing...'
			: status === 'error'
				? 'Retry Processing'
				: 'Process Corpus'
	);

	let isDisabled = $derived(disabled || status === 'processing');
</script>

<button class="process-btn" class:processing={status === 'processing'} disabled={isDisabled} {onclick}>
	{label}
</button>

<style>
	.process-btn {
		width: 100%;
		height: 44px;
		padding: 0 var(--lg);
		border-radius: 6px;
		font-size: 14px;
		font-weight: 600;
		background: var(--accent);
		color: #ffffff;
		border: none;
		cursor: pointer;
		transition: filter 150ms ease, opacity 150ms ease;
	}

	.process-btn:hover:not(:disabled) {
		filter: brightness(0.9);
	}

	.process-btn:active:not(:disabled) {
		transform: scale(0.98);
	}

	.process-btn:disabled {
		cursor: not-allowed;
	}

	.process-btn:disabled:not(.processing) {
		background: var(--surface3);
		color: var(--text-dim);
	}

	.process-btn.processing {
		opacity: 0.5;
	}
</style>
