<script lang="ts">
	import { selectedConcept } from '$lib/stores/tree';
	import { units, selectedUnit, navigateUnit, loading } from '$lib/stores/review';
	import { editorOpen } from '$lib/stores/review';
	import ConfidenceBadge from './ConfidenceBadge.svelte';
	import ReviewControls from './ReviewControls.svelte';
	import InlineEditor from './InlineEditor.svelte';
	import LoadingSkeleton from './LoadingSkeleton.svelte';
	import type { KnowledgeUnitResponse } from '$lib/api/client';

	const extractionPathColors: Record<string, string> = {
		entity_ruler: 'var(--cyan)',
		llm: 'var(--purple)',
		semantic: 'var(--path-semantic)',
		heading_context: 'var(--orange)',
	};

	const extractionPathLabels: Record<string, string> = {
		entity_ruler: 'EntityRuler',
		llm: 'LLM',
		semantic: 'Semantic',
		heading_context: 'Heading',
	};

	function selectUnit(unit: KnowledgeUnitResponse) {
		$selectedUnit = unit;
		$editorOpen = false;
	}

	function statusDotColor(status: string): string {
		if (status === 'approved') return 'var(--green)';
		if (status === 'rejected') return 'var(--red)';
		if (status === 'edited') return 'var(--accent)';
		return 'transparent';
	}

	function unitBg(status: string): string {
		if (status === 'approved') return 'var(--highlight-confirmed)';
		if (status === 'rejected') return 'var(--highlight-rejected)';
		return '';
	}

	function copyIri(iri: string) {
		navigator.clipboard.writeText(iri);
	}
</script>

<div class="detail-view">
	{#if !$selectedConcept}
		<div class="empty-state">
			<span class="empty-heading">No extraction data</span>
			<span class="empty-body">Select a concept from the FOLIO tree to view knowledge units.</span>
		</div>
	{:else if $loading}
		<LoadingSkeleton variant="detail" />
	{:else}
		<!-- Concept Header -->
		<div class="concept-header">
			<h2 class="concept-label">{$selectedConcept.label}</h2>
			{#if $selectedConcept.iri}
				<div class="concept-iri">
					<code>{$selectedConcept.iri}</code>
					<button
						class="copy-btn"
						onclick={() => copyIri($selectedConcept?.iri ?? '')}
						aria-label="Copy IRI"
						title="Copy IRI"
					>
						<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<rect x="9" y="9" width="13" height="13" rx="2" />
							<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
						</svg>
					</button>
				</div>
			{/if}
		</div>

		<!-- Unit List -->
		<div class="unit-list" role="list">
			{#each $units as unit (unit.id)}
				{@const isSelected = $selectedUnit?.id === unit.id}
				<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
				<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
				<div
					class="unit-card"
					class:selected={isSelected}
					role="listitem"
					style:background={unitBg(unit.review_status)}
					onclick={() => selectUnit(unit)}
					onkeydown={(e) => { if (e.key === 'Enter') selectUnit(unit); }}
					tabindex="0"
				>
					<!-- Status dot -->
					<div class="status-dot" style:background={statusDotColor(unit.review_status)}></div>

					<div class="unit-content">
						<!-- Unit text -->
						<p class="unit-text">
							{#if unit.review_status === 'edited' && unit.edited_text}
								{unit.edited_text}
							{:else}
								{unit.text}
							{/if}
						</p>

						<!-- Metadata row -->
						<div class="unit-meta">
							<span class="type-tag">{unit.unit_type}</span>
							<span class="novelty" title="Novelty score">N:{Math.round(unit.surprise_score * 100)}</span>

							<!-- Extraction path badges -->
							{#each unit.folio_tags as tag}
								<span
									class="path-badge"
									style:background="rgba({extractionPathColors[tag.extraction_path] ?? 'var(--text-dim)'}, 0.15)"
									style:color={extractionPathColors[tag.extraction_path] ?? 'var(--text-dim)'}
								>
									{extractionPathLabels[tag.extraction_path] ?? tag.extraction_path}
								</span>
							{/each}

							<ConfidenceBadge score={unit.confidence} />
						</div>

						<!-- Review controls for selected unit -->
						{#if isSelected}
							<ReviewControls unitId={unit.id} />
							<InlineEditor unitId={unit.id} initialText={unit.edited_text ?? unit.text} />
						{/if}
					</div>
				</div>
			{/each}
		</div>

		{#if $units.length === 0}
			<div class="empty-state">
				<span class="empty-body">No knowledge units for this concept at the current filter.</span>
			</div>
		{/if}
	{/if}
</div>

<style>
	.detail-view {
		height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.concept-header {
		padding: var(--md);
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.concept-label {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.3px;
	}

	.concept-iri {
		display: flex;
		align-items: center;
		gap: var(--xs);
		margin-top: var(--xs);
	}

	.concept-iri code {
		font-size: 11px;
		font-family: monospace;
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.copy-btn {
		flex-shrink: 0;
		color: var(--text-dim);
		padding: 2px;
	}

	.copy-btn:hover {
		color: var(--accent);
	}

	.unit-list {
		flex: 1;
		overflow-y: auto;
		padding: var(--sm);
		display: flex;
		flex-direction: column;
		gap: var(--sm);
	}

	.unit-card {
		display: flex;
		gap: var(--sm);
		padding: var(--sm);
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 6px;
		cursor: pointer;
		transition: border-color 150ms, transform 200ms;
	}

	.unit-card:hover {
		border-color: var(--accent-dim);
	}

	.unit-card.selected {
		border-color: var(--accent);
	}

	.status-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
		margin-top: 6px;
	}

	.unit-content {
		flex: 1;
		min-width: 0;
	}

	.unit-text {
		font-size: 14px;
		line-height: 1.5;
		margin-bottom: var(--xs);
	}

	.unit-meta {
		display: flex;
		flex-wrap: wrap;
		gap: var(--xs);
		align-items: center;
		font-size: 11px;
		margin-bottom: var(--sm);
	}

	.type-tag {
		padding: 1px 6px;
		background: var(--surface3);
		border-radius: 3px;
		color: var(--text-dim);
		text-transform: uppercase;
		font-size: 10px;
		letter-spacing: 0.5px;
	}

	.novelty {
		color: var(--text-dim);
	}

	.path-badge {
		padding: 1px 6px;
		border-radius: 9999px;
		font-size: 11px;
		font-weight: 500;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: var(--sm);
		padding: var(--lg);
	}

	.empty-heading {
		font-size: 18px;
		font-weight: 600;
	}

	.empty-body {
		font-size: 14px;
		color: var(--text-dim);
		text-align: center;
	}
</style>
