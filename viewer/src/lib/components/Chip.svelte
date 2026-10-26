<script lang="ts">
	let {
		label, branch, tone = 'default', confidence = 'high', verdict = 'pending', onclick, pressed,
	}: {
		label: string;
		branch: string;
		tone?: 'default' | 'process' | 'evidence' | 'actor' | 'document';
		confidence?: 'high' | 'medium' | 'low';
		verdict?: 'pending' | 'correct' | 'uncertain' | 'wrong';
		onclick?: () => void;
		pressed?: boolean;
	} = $props();
	const states = {
		pending: { icon: '○', label: 'Pending' },
		correct: { icon: '✓', label: 'Correct' },
		uncertain: { icon: '?', label: 'Uncertain' },
		wrong: { icon: '×', label: 'Wrong' },
	};
</script>

{#snippet content()}
	<span class="branch-label">{branch}</span>
	<span>{label}</span>
	<span class="verdict {verdict}"><span aria-hidden="true">{states[verdict].icon}</span> {states[verdict].label}</span>
	<span class="confidence">{confidence} confidence</span>
{/snippet}

{#if onclick}
	<button type="button" class="chip {tone} {confidence}" {onclick} aria-pressed={pressed}>
		{@render content()}
	</button>
{:else}
	<span class="chip {tone} {confidence}">{@render content()}</span>
{/if}

<style>
	.chip {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--xs) var(--sm);
		max-width: 100%;
		padding: 6px 9px;
		border: 1px solid var(--border);
		border-left: 3px solid var(--branch, var(--gilt));
		border-radius: 4px;
		background: var(--bg);
		color: var(--text);
		font: 600 13px/1.5 var(--ui);
		text-align: left;
		overflow-wrap: anywhere;
	}
	button.chip { min-height: 42px; }
	button:hover, button[aria-pressed='true'] { background: var(--surface2); border-color: var(--gilt); }
	.branch-label { color: var(--branch, var(--gilt)); }
	.confidence { color: var(--text-dim); font-weight: 400; }
	.medium { border-top-style: dashed; border-bottom-style: dashed; }
	.low { border-style: dotted; }
	.process { --branch: var(--branch-process); }
	.evidence { --branch: var(--branch-evidence); }
	.actor { --branch: var(--branch-actor); }
	.document { --branch: var(--branch-document); }
</style>
