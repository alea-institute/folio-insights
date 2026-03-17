<script lang="ts">
	import { editorOpen, submitReview, selectedUnit } from '$lib/stores/review';

	let { unitId, initialText, corpus = 'default' }: { unitId: string; initialText: string; corpus?: string } = $props();

	let text = $state('');
	let charCount = $derived(text.length);

	// Sync text when initialText changes or editor opens
	$effect(() => {
		if ($editorOpen) {
			text = initialText;
		}
	});

	async function save() {
		await submitReview(unitId, 'edited', corpus, text);
		$editorOpen = false;
	}

	function discard() {
		text = initialText;
		$editorOpen = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			save();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			discard();
		}
	}
</script>

{#if $editorOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="editor" role="group" aria-label="Inline editor" onkeydown={handleKeydown}>
		<textarea
			bind:value={text}
			class="editor-textarea"
			aria-label="Edit knowledge unit text"
			rows="4"
		></textarea>
		<div class="editor-footer">
			<span class="char-count">{charCount} chars</span>
			<div class="editor-actions">
				<button class="btn-discard" onclick={discard}>Discard Edit</button>
				<button class="btn-save" onclick={save}>Save Edit</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.editor {
		margin-top: var(--sm);
		animation: expandIn 150ms ease-out;
	}

	@keyframes expandIn {
		from { max-height: 0; opacity: 0; }
		to { max-height: 400px; opacity: 1; }
	}

	.editor-textarea {
		width: 100%;
		padding: var(--sm);
		font-size: 14px;
		line-height: 1.5;
		background: var(--surface2);
		border: 2px solid var(--accent);
		border-radius: 4px;
		color: var(--text);
		resize: vertical;
		min-height: 80px;
	}

	.editor-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-top: var(--xs);
	}

	.char-count {
		font-size: 11px;
		color: var(--text-dim);
	}

	.editor-actions {
		display: flex;
		gap: var(--sm);
	}

	.btn-discard {
		font-size: 13px;
		color: var(--text-dim);
		padding: var(--xs) var(--sm);
	}

	.btn-save {
		font-size: 13px;
		font-weight: 600;
		padding: var(--xs) var(--sm);
		background: var(--accent);
		color: #fff;
		border-radius: 4px;
	}
</style>
