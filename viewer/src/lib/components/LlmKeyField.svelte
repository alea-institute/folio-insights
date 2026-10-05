<script lang="ts">
	import { llmKey, setLlmKey, clearLlmKey } from '$lib/stores/llmKey';

	const id = $props.id();
	let visible = $state(false);
</script>

<div class="key-field">
	<label for={id}>LLM API key</label>
	<div class="key-controls">
		<input
			{id}
			type={visible ? 'text' : 'password'}
			value={$llmKey}
			oninput={(event) => setLlmKey(event.currentTarget.value)}
			autocomplete="off"
			spellcheck="false"
			data-1p-ignore
			aria-describedby={`${id}-help`}
		/>
		<button type="button" aria-pressed={visible} onclick={() => visible = !visible}>
			{visible ? 'Hide' : 'Show'} key
		</button>
		<button type="button" disabled={!$llmKey} onclick={clearLlmKey}>Clear</button>
	</div>
	<p id={`${id}-help`}>Kept in this tab's memory only. Never saved.</p>
</div>

<style>
	.key-field {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
		font-size: 13px;
	}

	.key-controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sm);
	}

	input {
		flex: 1;
		min-width: 0;
		padding: var(--sm);
		background: var(--surface3);
		color: var(--text);
		border: 1px solid var(--text-dim);
		border-radius: 4px;
	}

	button {
		padding: var(--sm);
		background: var(--surface3);
		color: var(--accent);
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	button:disabled {
		color: var(--text-dim);
		cursor: not-allowed;
	}

	p {
		color: var(--text-dim);
		margin: 0;
	}
</style>
