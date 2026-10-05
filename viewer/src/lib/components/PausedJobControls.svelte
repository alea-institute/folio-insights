<script lang="ts">
	import { onDestroy } from 'svelte';
	import { resupplyCredentials, resumeJob } from '$lib/api/client';
	import { llmKey, controlTokens } from '$lib/stores/llmKey';
	import type { JobKind } from '$lib/stores/llmKey';

	let { corpusId, kind, status, reason, oncontinue }: {
		corpusId: string;
		kind: JobKind;
		status: 'needs_credentials' | 'budget_exhausted';
		reason?: string | null;
		oncontinue: () => void;
	} = $props();

	let active = true;
	onDestroy(() => { active = false; });
	let busy = $state(false);
	let error = $state<string | null>(null);
	let hasToken = $derived(Boolean($controlTokens[corpusId]?.[kind]));

	async function continueJob() {
		if (busy || !$llmKey || !hasToken) return;
		busy = true;
		error = null;
		const result = status === 'needs_credentials'
			? await resupplyCredentials(corpusId, kind)
			: await resumeJob(corpusId, kind);
		if (!active) return;
		busy = false;
		if ('error' in result) {
			error = result.error;
		} else {
			oncontinue();
		}
	}
</script>

<div class="paused-job">
	<div aria-live="polite">
		<p>
			{kind === 'processing' ? 'Processing' : 'Discovery'} paused:
			{status === 'needs_credentials' ? 'an LLM API key is needed to continue.' : 'the spending budget has been exhausted.'}
		</p>
		{#if reason}<p>Reason: {reason}</p>{/if}
		{#if !$llmKey}<p>Enter an LLM API key above to continue.</p>{/if}
		{#if !hasToken}
			<p>This tab has no control token for this job. Continue from the tab that started it; reloading clears the token.</p>
		{/if}
		{#if error}<p class="error-text">{error}</p>{/if}
	</div>
	<button type="button" disabled={busy || !$llmKey || !hasToken} onclick={continueJob}>
		{busy ? 'Continuing...' : status === 'needs_credentials' ? 'Supply key and continue' : 'Resume'}
	</button>
</div>

<style>
	.paused-job {
		font-size: 13px;
		color: var(--orange);
	}

	button {
		padding: var(--sm) var(--md);
		border: none;
		border-radius: 4px;
		background: var(--accent);
		color: #ffffff;
		cursor: pointer;
	}

	button:disabled {
		background: var(--surface3);
		color: var(--text-dim);
		cursor: not-allowed;
	}

	.error-text {
		color: var(--red);
		overflow-wrap: anywhere;
	}
</style>
