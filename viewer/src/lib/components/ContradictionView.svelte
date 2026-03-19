<script lang="ts">
	import { resolveContradiction, type ContradictionResponse } from '$lib/api/client';
	import { selectedCorpus } from '$lib/stores/corpus';
	import { selectedContradictionId, loadContradictions, taskAnnouncement } from '$lib/stores/tasks';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { contradiction }: { contradiction: ContradictionResponse } = $props();

	let mergeText = $state('');
	let showMergeEditor = $state(false);
	let resolving = $state(false);

	function typeColor(type: string): string {
		if (type === 'full') return 'var(--red)';
		return 'var(--orange)';
	}

	function typeBg(type: string): string {
		if (type === 'full') return 'rgba(224, 85, 85, 0.15)';
		return 'rgba(232, 165, 76, 0.15)';
	}

	function authorityColor(level: number): string {
		if (level >= 8) return 'var(--green)';
		if (level >= 5) return 'var(--orange)';
		return 'var(--text-dim)';
	}

	async function resolve(resolution: string) {
		const corpus = $selectedCorpus;
		if (!corpus || resolving) return;
		resolving = true;

		const resolvedText = resolution === 'merge' ? mergeText : undefined;
		const result = await resolveContradiction(
			corpus.id,
			contradiction.id,
			resolution,
			resolvedText
		);

		if (!('error' in result)) {
			$taskAnnouncement = `Contradiction resolved: ${resolution}`;
			$selectedContradictionId = null;
			showMergeEditor = false;
			mergeText = '';
			await loadContradictions(corpus.id);
		}

		resolving = false;
	}

	function startMerge() {
		showMergeEditor = true;
		mergeText = '';
	}
</script>

<div class="contradiction-view">
	<!-- Side-by-side columns -->
	<div class="contradiction-columns">
		<div class="contradiction-side">
			<span class="source-badge">{contradiction.source_a}</span>
			<div class="authority" style:color={authorityColor(contradiction.authority_a)}>
				Authority: {contradiction.authority_a}/10
			</div>
			<p class="unit-text">{contradiction.unit_text_a}</p>
			<div class="side-meta">
				<ConfidenceBadge score={contradiction.confidence_a} />
			</div>
		</div>

		<div class="contradiction-side">
			<span class="source-badge">{contradiction.source_b}</span>
			<div class="authority" style:color={authorityColor(contradiction.authority_b)}>
				Authority: {contradiction.authority_b}/10
			</div>
			<p class="unit-text">{contradiction.unit_text_b}</p>
			<div class="side-meta">
				<ConfidenceBadge score={contradiction.confidence_b} />
			</div>
		</div>
	</div>

	<!-- Metadata row -->
	<div class="contradiction-meta">
		<span
			class="type-pill"
			style:color={typeColor(contradiction.contradiction_type)}
			style:background={typeBg(contradiction.contradiction_type)}
		>
			{contradiction.contradiction_type.toUpperCase()}
		</span>
		<span class="nli-score">NLI: {Math.round(contradiction.nli_score * 100)}%</span>
	</div>

	<!-- Merge editor (if active) -->
	{#if showMergeEditor}
		<div class="merge-editor">
			<textarea
				bind:value={mergeText}
				placeholder="Write the merged statement that resolves both positions..."
				class="merge-textarea"
				rows={3}
			></textarea>
			<div class="merge-actions">
				<button class="btn btn-save" onclick={() => resolve('merge')} disabled={!mergeText.trim() || resolving}>
					Save Merged Statement
				</button>
				<button class="btn btn-cancel" onclick={() => (showMergeEditor = false)}>
					Cancel
				</button>
			</div>
		</div>
	{/if}

	<!-- Resolution buttons -->
	<div class="resolution-buttons" role="radiogroup" aria-label="Contradiction resolution">
		<button class="btn btn-keep" onclick={() => resolve('keep_both')} disabled={resolving}>
			Keep Both
		</button>
		<button class="btn btn-prefer" onclick={() => resolve('prefer_a')} disabled={resolving}>
			Prefer A
		</button>
		<button class="btn btn-prefer" onclick={() => resolve('prefer_b')} disabled={resolving}>
			Prefer B
		</button>
		<button class="btn btn-merge" onclick={startMerge} disabled={resolving}>
			Merge Statement
		</button>
		<button class="btn btn-jurisdiction" onclick={() => resolve('jurisdiction')} disabled={resolving}>
			Mark Jurisdictional
		</button>
	</div>
</div>

<style>
	.contradiction-view {
		padding: var(--sm);
		border: 1px solid var(--border);
		border-radius: 6px;
		margin-bottom: var(--sm);
	}

	.contradiction-columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--sm);
	}

	.contradiction-side {
		background: var(--contradiction);
		border-radius: 6px;
		padding: var(--sm);
	}

	.source-badge {
		display: inline-block;
		padding: 1px 6px;
		background: var(--surface3);
		border-radius: 9999px;
		font-size: 11px;
		color: var(--text-dim);
		margin-bottom: var(--xs);
	}

	.authority {
		font-size: 11px;
		margin-bottom: var(--xs);
	}

	.unit-text {
		font-size: 14px;
		line-height: 1.5;
		margin-bottom: var(--xs);
	}

	.side-meta {
		display: flex;
		align-items: center;
		gap: var(--xs);
	}

	.contradiction-meta {
		display: flex;
		align-items: center;
		gap: var(--sm);
		padding: var(--sm) 0;
		border-bottom: 1px solid var(--border);
	}

	.type-pill {
		padding: 1px 8px;
		border-radius: 9999px;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-weight: 600;
	}

	.nli-score {
		font-size: 11px;
		color: var(--text-dim);
	}

	.merge-editor {
		padding: var(--sm) 0;
	}

	.merge-textarea {
		width: 100%;
		padding: var(--sm);
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 14px;
		line-height: 1.5;
		resize: vertical;
	}

	.merge-textarea::placeholder {
		color: var(--text-dim);
	}

	.merge-actions {
		display: flex;
		gap: var(--xs);
		margin-top: var(--xs);
	}

	.resolution-buttons {
		display: flex;
		flex-wrap: wrap;
		gap: var(--xs);
		padding-top: var(--sm);
	}

	.btn {
		height: 36px;
		padding: 0 var(--sm);
		border-radius: 4px;
		font-size: 14px;
		font-weight: 600;
		background: transparent;
		transition: opacity 150ms;
	}

	.btn:hover:not(:disabled) {
		opacity: 0.85;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-keep {
		border: 1px solid var(--text-dim);
		color: var(--text-dim);
	}

	.btn-prefer {
		border: 1px solid var(--accent);
		color: var(--accent);
	}

	.btn-merge {
		border: 1px solid var(--orange);
		color: var(--orange);
	}

	.btn-jurisdiction {
		border: 1px solid var(--orange);
		color: var(--orange);
	}

	.btn-save {
		background: var(--green);
		color: #fff;
	}

	.btn-cancel {
		color: var(--text-dim);
	}
</style>
