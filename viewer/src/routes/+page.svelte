<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchTree } from '$lib/api/client';
	import { bulkApprove } from '$lib/api/client';
	import { treeData, selectedConcept, viewMode, confidenceFilter } from '$lib/stores/tree';
	import { loadUnits, selectedUnit, navigateUnit, submitReview, refreshStats, editorOpen, announcement } from '$lib/stores/review';
	import FolioTree from '$lib/components/FolioTree.svelte';
	import DetailView from '$lib/components/DetailView.svelte';
	import SourceContext from '$lib/components/SourceContext.svelte';
	import KeyboardShortcuts from '$lib/components/KeyboardShortcuts.svelte';
	import type { TreeNode } from '$lib/api/client';

	let leftWidth = $state(320);
	let topHeight = $state(60);
	let draggingH = $state(false);
	let draggingV = $state(false);
	let rightPaneEl: HTMLElement | undefined = $state();
	let focusedPane = $state<'tree' | 'detail' | 'source'>('tree');
	let shortcutsRef: KeyboardShortcuts | undefined = $state();

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
		// Don't intercept when typing in inputs/textareas
		const tag = (e.target as HTMLElement)?.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

		// Tab: cycle panes
		if (e.key === 'Tab' && !e.ctrlKey && !e.altKey && !e.metaKey) {
			e.preventDefault();
			if (focusedPane === 'tree') focusedPane = 'detail';
			else if (focusedPane === 'detail') focusedPane = 'source';
			else focusedPane = 'tree';
			return;
		}

		// ? : show shortcuts
		if (e.key === '?') {
			e.preventDefault();
			shortcutsRef?.toggle();
			return;
		}

		// Ctrl+F: focus tree filter
		if (e.key === 'f' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			const input = document.querySelector<HTMLInputElement>('.filter-input');
			input?.focus();
			return;
		}

		// Escape: close editor or modal
		if (e.key === 'Escape') {
			$editorOpen = false;
			shortcutsRef?.hide();
			return;
		}

		// If editor is open, don't intercept review shortcuts
		if ($editorOpen) return;

		// Confidence filter: 1/2/3/4
		if (e.key === '1') { $confidenceFilter = 'all'; return; }
		if (e.key === '2') { $confidenceFilter = 'high'; return; }
		if (e.key === '3') { $confidenceFilter = 'medium'; return; }
		if (e.key === '4') { $confidenceFilter = 'low'; return; }

		// Review shortcuts (only when detail pane focused or any for Shift+A)
		const unit = $selectedUnit;
		if (e.key === 'A' && e.shiftKey) {
			e.preventDefault();
			handleBulkApprove();
			return;
		}

		if (unit && (focusedPane === 'detail' || focusedPane === 'tree')) {
			if (e.key === 'a' || e.key === 'A') { submitReview(unit.id, 'approved'); return; }
			if (e.key === 'r' || e.key === 'R') { submitReview(unit.id, 'rejected'); return; }
			if (e.key === 'e' || e.key === 'E') { $editorOpen = true; return; }
			if (e.key === 's' || e.key === 'S') { navigateUnit('next'); return; }
		}

		// Navigation
		if (e.key === 'j' || e.key === 'ArrowDown') { navigateUnit('next'); return; }
		if (e.key === 'k' || e.key === 'ArrowUp') { navigateUnit('prev'); return; }
	}

	async function handleBulkApprove() {
		const result = await bulkApprove('default', undefined, 0.8);
		if (!('error' in result)) {
			await refreshStats('default');
			const concept = $selectedConcept;
			if (concept) {
				const conf = $confidenceFilter === 'all' ? undefined : $confidenceFilter;
				await loadUnits('default', concept.iri, conf);
			}
		}
	}

	function selectConcept(node: TreeNode) {
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

<!-- Aria-live region for announcements -->
<div class="sr-only" aria-live="polite" role="status">{$announcement}</div>

<div class="three-pane" class:dragging={draggingH || draggingV}>
	<!-- Left Pane: FOLIO Tree -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="pane pane-left"
		class:focused={focusedPane === 'tree'}
		style="width: {leftWidth}px"
		role="region"
		aria-label="FOLIO concept tree"
		onclick={() => (focusedPane = 'tree')}
	>
		<FolioTree onselectconcept={selectConcept} />
	</div>

	<!-- Horizontal Divider -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
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
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="pane pane-detail"
			class:focused={focusedPane === 'detail'}
			style="height: {topHeight}%"
			role="region"
			aria-label="Knowledge unit detail"
			onclick={() => (focusedPane = 'detail')}
		>
			<DetailView />
		</div>

		<!-- Vertical Divider -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="divider divider-v"
			class:active={draggingV}
			role="separator"
			aria-orientation="horizontal"
			onmousedown={handleVDragStart}
		></div>

		<!-- Lower Right: Source Context -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="pane pane-source"
			class:focused={focusedPane === 'source'}
			style="height: {100 - topHeight}%"
			role="region"
			aria-label="Source context"
			onclick={() => (focusedPane = 'source')}
		>
			<SourceContext />
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

<!-- Keyboard shortcuts modal -->
<KeyboardShortcuts bind:this={shortcutsRef} />

<style>
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

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
