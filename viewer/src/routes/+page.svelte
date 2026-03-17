<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchTree } from '$lib/api/client';
	import { treeData, selectedConcept, viewMode, confidenceFilter } from '$lib/stores/tree';
	import { loadUnits, selectedUnit } from '$lib/stores/review';

	let leftWidth = $state(320);
	let topHeight = $state(60);
	let draggingH = $state(false);
	let draggingV = $state(false);
	let rightPaneEl: HTMLElement | undefined = $state();
	let focusedPane = $state<'tree' | 'detail' | 'source'>('tree');

	const LEFT_MIN = 240;
	const TOP_MIN_PCT = 20;
	const TOP_MAX_PCT = 80;

	onMount(async () => {
		const result = await fetchTree('default');
		if (!('error' in result)) {
			$treeData = result;
		}
	});

	function handleHDragStart(e: MouseEvent) {
		draggingH = true;
		e.preventDefault();
		const onMove = (ev: MouseEvent) => {
			leftWidth = Math.max(LEFT_MIN, ev.clientX);
		};
		const onUp = () => {
			draggingH = false;
			window.removeEventListener('mousemove', onMove);
			window.removeEventListener('mouseup', onUp);
		};
		window.addEventListener('mousemove', onMove);
		window.addEventListener('mouseup', onUp);
	}

	function handleVDragStart(e: MouseEvent) {
		draggingV = true;
		e.preventDefault();
		const onMove = (ev: MouseEvent) => {
			if (!rightPaneEl) return;
			const rect = rightPaneEl.getBoundingClientRect();
			const pct = ((ev.clientY - rect.top) / rect.height) * 100;
			topHeight = Math.min(TOP_MAX_PCT, Math.max(TOP_MIN_PCT, pct));
		};
		const onUp = () => {
			draggingV = false;
			window.removeEventListener('mousemove', onMove);
			window.removeEventListener('mouseup', onUp);
		};
		window.addEventListener('mousemove', onMove);
		window.addEventListener('mouseup', onUp);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Tab' && !e.ctrlKey && !e.altKey && !e.metaKey) {
			e.preventDefault();
			if (focusedPane === 'tree') focusedPane = 'detail';
			else if (focusedPane === 'detail') focusedPane = 'source';
			else focusedPane = 'tree';
		}
	}

	function selectConcept(node: typeof $selectedConcept) {
		$selectedConcept = node;
		if (node) {
			const confValue = $confidenceFilter === 'all' ? undefined : $confidenceFilter;
			loadUnits('default', node.iri, confValue);
		}
		focusedPane = 'detail';
	}

	// Reactivity: when confidence filter changes, reload units
	$effect(() => {
		const conf = $confidenceFilter;
		const concept = $selectedConcept;
		if (concept) {
			const confValue = conf === 'all' ? undefined : conf;
			loadUnits('default', concept.iri, confValue);
		}
	});
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="three-pane" class:dragging={draggingH || draggingV}>
	<!-- Left Pane: FOLIO Tree -->
	<div
		class="pane pane-left"
		class:focused={focusedPane === 'tree'}
		style="width: {leftWidth}px"
		role="region"
		aria-label="FOLIO concept tree"
		onclick={() => (focusedPane = 'tree')}
	>
		<div class="pane-placeholder">
			<span class="placeholder-label">FOLIO Concept Tree</span>
			<span class="placeholder-hint">Component loads in Task 3</span>
		</div>
	</div>

	<!-- Horizontal Divider -->
	<div
		class="divider divider-h"
		class:active={draggingH}
		role="separator"
		aria-orientation="vertical"
		onmousedown={handleHDragStart}
	></div>

	<!-- Right Area -->
	<div class="pane-right" bind:this={rightPaneEl}>
		<!-- Upper Right: Detail View -->
		<div
			class="pane pane-detail"
			class:focused={focusedPane === 'detail'}
			style="height: {topHeight}%"
			role="region"
			aria-label="Knowledge unit detail"
			onclick={() => (focusedPane = 'detail')}
		>
			<div class="pane-placeholder">
				<span class="placeholder-label">Detail View</span>
				<span class="placeholder-hint">
					{#if $selectedConcept}
						Selected: {$selectedConcept.label}
					{:else}
						Select a concept from the tree
					{/if}
				</span>
			</div>
		</div>

		<!-- Vertical Divider -->
		<div
			class="divider divider-v"
			class:active={draggingV}
			role="separator"
			aria-orientation="horizontal"
			onmousedown={handleVDragStart}
		></div>

		<!-- Lower Right: Source Context -->
		<div
			class="pane pane-source"
			class:focused={focusedPane === 'source'}
			style="height: {100 - topHeight}%"
			role="region"
			aria-label="Source context"
			onclick={() => (focusedPane = 'source')}
		>
			<div class="pane-placeholder">
				<span class="placeholder-label">Source Context</span>
				<span class="placeholder-hint">
					{#if $selectedUnit}
						{$selectedUnit.source_file}
					{:else}
						Select a unit to view source
					{/if}
				</span>
			</div>
		</div>
	</div>
</div>

<!-- View mode toggle -->
<div class="view-toggle">
	<button
		class:active={$viewMode === 'tree'}
		onclick={() => ($viewMode = 'tree')}
		aria-label="Tree view"
	>
		<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<path d="M3 3h18v18H3zM3 9h18M9 3v18" />
		</svg>
	</button>
	<button
		class:active={$viewMode === 'list'}
		onclick={() => ($viewMode = 'list')}
		aria-label="List view"
	>
		<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
		</svg>
	</button>
</div>

<style>
	.three-pane {
		display: flex;
		height: 100%;
		overflow: hidden;
	}

	.three-pane.dragging {
		cursor: col-resize;
		user-select: none;
	}

	.pane {
		overflow: auto;
		background: var(--surface);
		position: relative;
	}

	.pane.focused {
		outline: 1px solid var(--accent);
	}

	.pane-left {
		flex-shrink: 0;
		min-width: 240px;
		border-right: 1px solid var(--border);
	}

	.pane-right {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.pane-detail {
		min-height: 200px;
		overflow: auto;
	}

	.pane-source {
		min-height: 120px;
		overflow: auto;
		border-top: 1px solid var(--border);
	}

	/* Dividers */
	.divider {
		flex-shrink: 0;
		background: var(--border);
		transition: background 150ms;
		z-index: 10;
	}

	.divider:hover,
	.divider.active {
		background: var(--accent);
	}

	.divider-h {
		width: 4px;
		cursor: col-resize;
	}

	.divider-v {
		height: 4px;
		cursor: row-resize;
	}

	/* Placeholders */
	.pane-placeholder {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: var(--sm);
	}

	.placeholder-label {
		font-size: 14px;
		font-weight: 600;
		color: var(--text-dim);
	}

	.placeholder-hint {
		font-size: 13px;
		color: var(--text-dim);
		opacity: 0.6;
	}

	/* View toggle */
	.view-toggle {
		position: fixed;
		bottom: var(--md);
		right: var(--md);
		display: flex;
		gap: 2px;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 2px;
	}

	.view-toggle button {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--xs) var(--sm);
		border-radius: 4px;
		color: var(--text-dim);
		transition: background 150ms, color 150ms;
	}

	.view-toggle button:hover {
		color: var(--text);
	}

	.view-toggle button.active {
		background: var(--accent);
		color: #fff;
	}
</style>
