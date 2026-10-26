<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		title, verdict = 'pending', reason, children, actions,
	}: {
		title: string;
		verdict?: 'pending' | 'correct' | 'uncertain' | 'wrong';
		reason?: string;
		children?: Snippet;
		actions?: Snippet;
	} = $props();
	const states = {
		pending: { icon: '○', label: 'Pending' },
		correct: { icon: '✓', label: 'Correct' },
		uncertain: { icon: '?', label: 'Uncertain' },
		wrong: { icon: '×', label: 'Wrong' },
	};
</script>

<article class="review-card" aria-label={title}>
	<header>
		<h3>{title}</h3>
		<span class="verdict {verdict}"><span aria-hidden="true">{states[verdict].icon}</span> {states[verdict].label}</span>
	</header>
	{#if reason}<p class="reason">{reason}</p>{/if}
	{#if children}<div class="card-content">{@render children()}</div>{/if}
	{#if actions}<footer class="card-actions">{@render actions()}</footer>{/if}
</article>

<style>
	.review-card {
		min-width: 0;
		padding: var(--lg);
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		overflow-wrap: anywhere;
	}
	header { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--sm) var(--md); }
	h3 { flex: 1 1 16ch; font: 600 26px/1.2 var(--reading); color: var(--paper); }
	.reason { margin-top: var(--md); color: var(--text-dim); }
	.card-content { display: flex; flex-wrap: wrap; gap: var(--sm); margin-top: var(--md); }
	.card-actions { display: flex; flex-wrap: wrap; gap: var(--sm); margin-top: var(--lg); }
	.card-actions :global(button) {
		min-height: 42px;
		padding: var(--sm) var(--md);
		border: 1px solid var(--gilt-line);
		border-radius: 4px;
		background: var(--kernel-bg);
		color: var(--gilt);
	}
	.card-actions :global(button:hover) { background: var(--surface2); }
</style>
