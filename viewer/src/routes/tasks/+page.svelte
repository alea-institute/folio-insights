<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		taskTreeData,
		selectedTaskId,
		taskTreeMode,
		loadTaskTree,
		loadTaskDetail,
		loadTaskUnits,
		loadContradictions,
		loadDiscoveryStats,
		discoveryStats,
		submitTaskReview,
		taskAnnouncement,
		unitTypeFilter,
		confidenceBandFilter,
		reviewStatusFilter,
		flagFilter,
	} from '$lib/stores/tasks';
	import { selectedCorpus } from '$lib/stores/corpus';
	import { createTask, bulkApproveTasks } from '$lib/api/client';
	import type { TaskTreeNode } from '$lib/api/client';
	import TaskTree from '$lib/components/TaskTree.svelte';
	import TaskDetail from '$lib/components/TaskDetail.svelte';
	import DiscoveryEvidence from '$lib/components/DiscoveryEvidence.svelte';
	import TaskDashboard from '$lib/components/TaskDashboard.svelte';
	import ManualTaskDialog from '$lib/components/ManualTaskDialog.svelte';
	import ExportDialog from '$lib/components/ExportDialog.svelte';
	import KeyboardShortcuts from '$lib/components/KeyboardShortcuts.svelte';

	let leftWidth = $state(320);
	let topHeight = $state(60);
	let draggingH = $state(false);
	let draggingV = $state(false);
	let rightPaneEl: HTMLElement | undefined = $state();
	let focusedPane = $state<'tree' | 'detail' | 'evidence'>('tree');
	let showDashboard = $state(false);
	let showManualTaskDialog = $state(false);
	let showExportDialog = $state(false);
	let shortcutsRef: KeyboardShortcuts | undefined = $state();

	let hasApprovedTasks = $derived($taskTreeData.some((n) => n.is_task && n.review_status === 'complete'));

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
		window.addEventListener('toggle-task-dashboard', toggleDashboard);
	});

	onDestroy(() => {
		window.removeEventListener('toggle-task-dashboard', toggleDashboard);
	});

	function toggleDashboard() {
		showDashboard = !showDashboard;
	}

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

	async function handleCreateTask(label: string, parentTaskId: string | null, taskType: string) {
		if (!corpusId) return;
		const result = await createTask(corpusId, label, undefined, parentTaskId ?? undefined);
		if (!('error' in result)) {
			$taskAnnouncement = `Task "${label}" created.`;
			showManualTaskDialog = false;
			const mode = $taskTreeMode === 'tasks_only' ? 'tasks_only' : undefined;
			await loadTaskTree(corpusId, mode);
		}
	}

	async function handleBulkApprove() {
		if (!corpusId) return;
		const result = await bulkApproveTasks(corpusId, undefined, 0.7);
		if (!('error' in result)) {
			$taskAnnouncement = `${result.approved_count} high-confidence tasks approved.`;
			const mode = $taskTreeMode === 'tasks_only' ? 'tasks_only' : undefined;
			await loadTaskTree(corpusId, mode);
			await loadDiscoveryStats(corpusId);
		}
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
			return;
		}

		// ?: toggle keyboard shortcuts
		if (e.key === '?') {
			e.preventDefault();
			shortcutsRef?.toggle();
			return;
		}

		// Escape: close modals/dashboard
		if (e.key === 'Escape') {
			if (showExportDialog) { showExportDialog = false; return; }
			if (showDashboard) { showDashboard = false; return; }
			if (showManualTaskDialog) { showManualTaskDialog = false; return; }
			return;
		}

		// x: open export dialog
		if (e.key === 'x' && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
			if (corpusId && !showExportDialog && !showManualTaskDialog) {
				showExportDialog = true;
			}
			return;
		}

		// a/A: approve selected task
		if (e.key === 'a' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
			if ($selectedTaskId && corpusId) {
				submitTaskReview(corpusId, $selectedTaskId, 'approved');
			}
			return;
		}

		// Shift+A: bulk approve high-confidence
		if (e.key === 'A' && e.shiftKey) {
			handleBulkApprove();
			return;
		}

		// r/R: reject selected task
		if ((e.key === 'r' || e.key === 'R') && !e.ctrlKey && !e.metaKey) {
			if ($selectedTaskId && corpusId) {
				submitTaskReview(corpusId, $selectedTaskId, 'rejected');
			}
			return;
		}

		// e/E: open inline editor (placeholder, handled by TaskDetail)
		if ((e.key === 'e' || e.key === 'E') && !e.ctrlKey && !e.metaKey) {
			// TaskDetail component handles inline editing internally
			return;
		}

		// m/M: move mode (placeholder announcement)
		if ((e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.metaKey) {
			if ($selectedTaskId) {
				$taskAnnouncement = 'Move mode: click a task to move the selected task under it.';
			}
			return;
		}

		// g/G: merge dialog (placeholder announcement)
		if ((e.key === 'g' || e.key === 'G') && !e.ctrlKey && !e.metaKey) {
			if ($selectedTaskId) {
				$taskAnnouncement = 'Merge mode: select a target task to merge into.';
			}
			return;
		}

		// j/ArrowDown: next task
		if (e.key === 'j' || e.key === 'ArrowDown') {
			navigateTask(1);
			return;
		}

		// k/ArrowUp: previous task
		if (e.key === 'k' || e.key === 'ArrowUp') {
			navigateTask(-1);
			return;
		}

		// Ctrl+F / Cmd+F: focus tree search
		if (e.key === 'f' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			const searchInput = document.querySelector<HTMLInputElement>('.tree-search-input');
			searchInput?.focus();
			return;
		}

		// 1/2/3/4: confidence filter shortcuts
		if (e.key === '1') { $confidenceBandFilter = 'all'; return; }
		if (e.key === '2') { $confidenceBandFilter = 'high'; return; }
		if (e.key === '3') { $confidenceBandFilter = 'medium'; return; }
		if (e.key === '4') { $confidenceBandFilter = 'low'; return; }
	}

	function navigateTask(direction: number) {
		const nodes = $taskTreeData.filter((n) => n.is_task);
		if (nodes.length === 0) return;
		const currentIdx = nodes.findIndex((n) => n.id === $selectedTaskId);
		const nextIdx = Math.max(0, Math.min(nodes.length - 1, currentIdx + direction));
		$selectedTaskId = nodes[nextIdx].id;
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
		<div class="tree-header">
			<button
				class="export-btn"
				onclick={() => (showExportDialog = true)}
				disabled={!corpusId}
				aria-label="Export ontology"
			>
				<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M6 1v7M3 5l3 3 3-3M2 10h8" />
				</svg>
				Export
			</button>
			<button class="new-task-btn" onclick={() => (showManualTaskDialog = true)} aria-label="Create new task">
				<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M6 1v10M1 6h10" />
				</svg>
				New Task
			</button>
		</div>
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

<!-- Task Dashboard overlay -->
{#if $discoveryStats}
	<TaskDashboard stats={$discoveryStats} visible={showDashboard} onclose={() => (showDashboard = false)} />
{/if}

<!-- Manual Task Dialog -->
<ManualTaskDialog
	open={showManualTaskDialog}
	treeNodes={$taskTreeData}
	oncreate={handleCreateTask}
	ondismiss={() => (showManualTaskDialog = false)}
/>

<!-- Export Dialog -->
<ExportDialog
	open={showExportDialog}
	corpusId={corpusId}
	hasApprovedTasks={hasApprovedTasks}
	ondismiss={() => (showExportDialog = false)}
/>

<!-- Keyboard Shortcuts Modal -->
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
		min-width: 280px;
		max-width: 480px;
		border-right: 1px solid var(--border);
		display: flex;
		flex-direction: column;
	}

	.tree-header {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		padding: var(--xs) var(--sm);
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.export-btn {
		display: flex;
		align-items: center;
		gap: var(--xs);
		padding: var(--xs) var(--sm);
		font-size: 11px;
		font-weight: 600;
		color: var(--accent);
		background: transparent;
		border: 1px solid var(--accent-dim);
		border-radius: 4px;
		cursor: pointer;
		transition: background 150ms ease;
	}

	.export-btn:hover:not(:disabled) {
		background: var(--highlight);
	}

	.export-btn:disabled {
		background: var(--surface3);
		color: var(--text-dim);
		cursor: not-allowed;
		border-color: var(--border);
	}

	.new-task-btn {
		display: flex;
		align-items: center;
		gap: var(--xs);
		padding: var(--xs) var(--sm);
		font-size: 11px;
		font-weight: 600;
		color: var(--accent);
		background: transparent;
		border: 1px solid var(--accent-dim);
		border-radius: 4px;
		cursor: pointer;
		transition: background 150ms ease;
	}

	.new-task-btn:hover {
		background: var(--highlight);
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
