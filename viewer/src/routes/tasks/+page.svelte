<script lang="ts">
	import { onMount } from 'svelte';
	import {
		taskTreeData,
		selectedTaskId,
		taskTreeMode,
		loadTaskTree,
		loadTaskDetail,
		loadTaskUnits,
		loadContradictions,
		loadDiscoveryStats,
		taskAnnouncement,
	} from '$lib/stores/tasks';
	import { selectedCorpus } from '$lib/stores/corpus';
	import TaskTree from '$lib/components/TaskTree.svelte';
	import TaskDetail from '$lib/components/TaskDetail.svelte';
	import DiscoveryEvidence from '$lib/components/DiscoveryEvidence.svelte';
	import type { TaskTreeNode } from '$lib/api/client';

	let leftWidth = $state(320);
	let topHeight = $state(60);
	let draggingH = $state(false);
	let draggingV = $state(false);
	let rightPaneEl: HTMLElement | undefined = $state();
	let focusedPane = $state<'tree' | 'detail' | 'evidence'>('tree');

	const LEFT_MIN = 280;
	const LEFT_MAX = 480;
	const TOP_MIN_PCT = 20;
	const TOP_MAX_PCT = 80;

	let corpusId = $derived($selectedCorpus?.id ?? '');

	onMount(async () => {
		if (corpusId) {
			const mode = $taskTreeMode === 'tasks_only' ? 'tasks_only' : undefined;
			await loadTaskTree(corpusId, mode);
			await loadContradictions(corpusId);
			await loadDiscoveryStats(corpusId);
		}
	});

	// Reload tree when corpus changes
	$effect(() => {
		const sc = $selectedCorpus;
		if (sc) {
			const mode = $taskTreeMode === 'tasks_only' ? 'tasks_only' : undefined;
			loadTaskTree(sc.id, mode);
			loadContradictions(sc.id);
			loadDiscoveryStats(sc.id);
		}
	});

	// Load detail when selectedTaskId changes
	$effect(() => {
		const taskId = $selectedTaskId;
		const sc = $selectedCorpus;
		if (taskId && sc) {
			loadTaskDetail(sc.id, taskId);
			loadTaskUnits(sc.id, taskId);
		}
	});

	function selectTask(node: TaskTreeNode) {
		$selectedTaskId = node.id;
		focusedPane = 'detail';
	}

	// --- Divider drag handlers ---
	function handleHDragStart(e: MouseEvent) {
		draggingH = true;
		e.preventDefault();
		const onMove = (ev: MouseEvent) => {
			leftWidth = Math.max(LEFT_MIN, Math.min(LEFT_MAX, ev.clientX));
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
		const tag = (e.target as HTMLElement)?.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

		// Tab: cycle panes
		if (e.key === 'Tab' && !e.ctrlKey && !e.altKey && !e.metaKey) {
			e.preventDefault();
			if (focusedPane === 'tree') focusedPane = 'detail';
			else if (focusedPane === 'detail') focusedPane = 'evidence';
			else focusedPane = 'tree';
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Aria-live region for announcements -->
<div class="sr-only" aria-live="polite" role="status">{$taskAnnouncement}</div>

<div class="three-pane" class:dragging={draggingH || draggingV}>
	<!-- Left Pane: Task Tree -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="pane pane-left"
		class:focused={focusedPane === 'tree'}
		style="width: {leftWidth}px"
		role="region"
		aria-label="Task hierarchy tree"
		onclick={() => (focusedPane = 'tree')}
	>
		<TaskTree onselecttask={selectTask} />
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
		<!-- Upper Right: Task Detail -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="pane pane-detail"
			class:focused={focusedPane === 'detail'}
			style="height: {topHeight}%"
			role="region"
			aria-label="Task detail and knowledge units"
			onclick={() => (focusedPane = 'detail')}
		>
			<TaskDetail />
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

		<!-- Lower Right: Discovery Evidence -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="pane pane-evidence"
			class:focused={focusedPane === 'evidence'}
			style="height: {100 - topHeight}%"
			role="region"
			aria-label="Discovery evidence"
			onclick={() => (focusedPane = 'evidence')}
		>
			<DiscoveryEvidence />
		</div>
	</div>
</div>

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
		min-width: 280px;
		max-width: 480px;
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

	.pane-evidence {
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
</style>
