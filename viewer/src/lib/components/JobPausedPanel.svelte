<script lang="ts">
	import type { PauseReason } from '$lib/stores/jobStatus';

	let {
		jobLabel,
		reason,
		detail = null,
		canControl,
		keyHeld,
		busy = false,
		error = null,
		oncontinue,
		oncancel,
	}: {
		/** "Processing" or "Task discovery". */
		jobLabel: string;
		reason: PauseReason;
		detail?: string | null;
		/** False when this tab no longer holds the job's control token. */
		canControl: boolean;
		keyHeld: boolean;
		busy?: boolean;
		error?: string | null;
		oncontinue: () => void;
		oncancel: () => void;
	} = $props();

	let heading = $derived(
		reason === 'needs_credentials'
			? `${jobLabel} is paused: it needs your API key`
			: `${jobLabel} is paused: it reached its spend cap`
	);

	let body = $derived(
		reason === 'needs_credentials'
			? keyHeld
				? 'The server does not hold a key for this job. Send the key held in this tab to continue.'
				: 'Keys live only in tab memory, so the server cannot continue without you. Enter your key to continue.'
			: 'The server dropped the key when the cap was reached. To continue, set a higher cap and supply your key; whoever resumes pays for the rest of the job.'
	);

	const headingId = `paused-heading-${Math.random().toString(36).slice(2, 8)}`;

	let actionLabel = $derived(reason === 'needs_credentials' ? 'Supply key and continue' : 'Raise cap and resume');
</script>

<section class="paused" aria-labelledby={headingId}>
	<h3 id={headingId} class="heading">{heading}</h3>
	<p class="body">{body}</p>
	{#if detail}
		<p class="detail">{detail}</p>
	{/if}

	{#if canControl}
		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}
		<div class="actions">
			<button type="button" class="btn btn-accent" onclick={oncontinue} disabled={busy}>
				{actionLabel}
			</button>
			<button type="button" class="btn btn-quiet" onclick={oncancel} disabled={busy} aria-busy={busy}>
				{busy ? 'Cancelling...' : 'Cancel job'}
			</button>
		</div>
	{:else}
		<p class="body">
			This tab no longer holds the job's control token (it lives only in the tab that started
			the job, and a reload clears it), so the job cannot be resumed or cancelled from here.
		</p>
	{/if}
</section>

<style>
	.paused {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
		padding: var(--md);
		background: var(--surface);
		border: 1px solid var(--border);
		border-left: 3px solid var(--orange);
		border-radius: 6px;
	}

	.heading {
		font-size: 14px;
		font-weight: 600;
		color: var(--orange);
	}

	.body {
		font-size: 13px;
		color: var(--text-dim);
		line-height: 1.5;
		max-width: 68ch;
	}

	.detail {
		font-size: 12px;
		color: var(--text-dim);
		overflow-wrap: anywhere;
	}

	.error {
		font-size: 13px;
		color: var(--red);
		padding: var(--xs) var(--sm);
		background: rgba(224, 85, 85, 0.08);
		border: 1px solid rgba(224, 85, 85, 0.25);
		border-radius: 4px;
		overflow-wrap: anywhere;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sm);
	}

	.btn {
		height: 32px;
		padding: 0 var(--md);
		font-size: 13px;
		border-radius: 4px;
		transition: opacity 150ms ease;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-accent {
		background: var(--accent);
		color: #fff;
		font-weight: 600;
	}

	.btn-accent:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-quiet {
		color: var(--text-dim);
		border: 1px solid var(--border);
	}

	.btn-quiet:hover:not(:disabled) {
		color: var(--text);
	}
</style>
