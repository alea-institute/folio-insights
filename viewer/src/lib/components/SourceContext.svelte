<script lang="ts">
	import { selectedUnit } from '$lib/stores/review';
	import { fetchSource, type SourceResponse } from '$lib/api/client';
	import LoadingSkeleton from './LoadingSkeleton.svelte';

	let sourceData = $state<SourceResponse | null>(null);
	let loadingSource = $state(false);

	$effect(() => {
		const unit = $selectedUnit;
		if (unit) {
			loadSource(unit.original_span.source_file, unit.original_span.start, unit.original_span.end);
		} else {
			sourceData = null;
		}
	});

	async function loadSource(file: string, start: number, end: number) {
		loadingSource = true;
		const result = await fetchSource(file, start, end);
		if ('error' in result) {
			sourceData = { found: false, file_path: file, section_breadcrumb: '', text: '', message: 'Source file not available' };
		} else {
			sourceData = result;
		}
		loadingSource = false;
	}

	function highlightedHtml(text: string, spanStart: number | undefined, spanEnd: number | undefined): string {
		if (spanStart === undefined || spanEnd === undefined || spanStart >= spanEnd) {
			return escapeHtml(text);
		}
		const before = escapeHtml(text.slice(0, spanStart));
		const span = escapeHtml(text.slice(spanStart, spanEnd));
		const after = escapeHtml(text.slice(spanEnd));
		return `${before}<mark class="highlight">${span}</mark>${after}`;
	}

	function escapeHtml(str: string): string {
		return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
	}
</script>

<div class="source-context">
	<div class="source-header">
		<span class="source-title">Source Context</span>
		{#if sourceData?.file_path}
			<span class="source-path">{sourceData.file_path}</span>
		{/if}
	</div>

	{#if loadingSource}
		<LoadingSkeleton variant="source" />
	{:else if !$selectedUnit}
		<div class="source-empty">
			<span>Select a unit to view source context</span>
		</div>
	{:else if !sourceData?.found}
		<div class="source-missing">
			<em>Source file not available on disk</em>
			{#if sourceData?.file_path}
				<span class="source-path-missing">{sourceData.file_path}</span>
			{/if}
			<span class="source-hint">The original file may have been moved or renamed.</span>
		</div>
	{:else}
		{#if sourceData.section_breadcrumb}
			<div class="breadcrumb">{sourceData.section_breadcrumb}</div>
		{/if}
		{#if $selectedUnit?.source_section?.length}
			<div class="breadcrumb">{$selectedUnit.source_section.join(' > ')}</div>
		{/if}
		<div class="source-text">
			{@html highlightedHtml(sourceData.text, sourceData.span_start_in_context, sourceData.span_end_in_context)}
		</div>
	{/if}
</div>

<style>
	.source-context {
		height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.source-header {
		display: flex;
		align-items: baseline;
		gap: var(--sm);
		padding: var(--sm) var(--md);
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.source-title {
		font-size: 14px;
		font-weight: 600;
	}

	.source-path {
		font-size: 11px;
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.breadcrumb {
		font-size: 11px;
		color: var(--text-dim);
		padding: var(--xs) var(--md);
	}

	.source-text {
		flex: 1;
		overflow-y: auto;
		padding: var(--md);
		font-size: 14px;
		line-height: 1.5;
		background: var(--bg);
		white-space: pre-wrap;
		word-break: break-word;
	}

	:global(.highlight) {
		background: var(--highlight);
		border-radius: 2px;
		padding: 1px 2px;
	}

	.source-empty,
	.source-missing {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: var(--sm);
		padding: var(--lg);
		color: var(--text-dim);
		font-size: 14px;
	}

	.source-missing em {
		font-style: italic;
	}

	.source-path-missing {
		font-size: 11px;
		font-family: monospace;
		color: var(--text-dim);
	}

	.source-hint {
		font-size: 13px;
		color: var(--text-dim);
	}
</style>
