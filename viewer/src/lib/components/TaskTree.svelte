<script lang="ts">
	import { Tree, type LTreeNode } from '@keenmate/svelte-treeview';
	import {
		taskTreeData,
		selectedTaskId,
		taskTreeMode,
		taskSearchText,
		loadTaskTree,
	} from '$lib/stores/tasks';
	import { selectedCorpus } from '$lib/stores/corpus';
	import { submitHierarchyEdit, type TaskTreeNode } from '$lib/api/client';

	let { onselecttask }: { onselecttask?: (node: TaskTreeNode) => void } = $props();

	// Use $state.raw for large datasets (per RESEARCH pitfall #6)
	let treeData = $state.raw<TaskTreeNode[]>([]);
	let selectedNode = $state<LTreeNode<TaskTreeNode> | null>(null);
	let searchText = $state<string>('');
	let treeRef: ReturnType<typeof Tree<TaskTreeNode>> | undefined = $state();

	// Sync treeData with store
	$effect(() => {
		treeData = $taskTreeData;
	});

	// Sync search text with store
	$effect(() => {
		searchText = $taskSearchText;
	});

	// When selectedNode changes, update store and call callback
	$effect(() => {
		if (selectedNode?.data) {
			const taskNode = selectedNode.data;
			$selectedTaskId = taskNode.id;
			onselecttask?.(taskNode);
		}
	});

	function handleModeChange(mode: 'tasks_only' | 'all_concepts') {
		$taskTreeMode = mode;
		const corpus = $selectedCorpus;
		if (corpus) {
			loadTaskTree(corpus.id, mode);
		}
	}

	async function handleNodeDrop(
		dropNode: LTreeNode<TaskTreeNode> | null,
		draggedNode: LTreeNode<TaskTreeNode>,
		position: 'above' | 'below' | 'child'
	) {
		const corpus = $selectedCorpus;
		if (!corpus || !dropNode?.data || !draggedNode?.data) return;
		await submitHierarchyEdit(
			corpus.id,
			'move',
			draggedNode.data.id,
			dropNode.data.id,
			position
		);
	}
</script>

<div class="task-tree">
	<!-- Search input -->
	<div class="tree-filter">
		<input
			type="text"
			placeholder="Search tasks..."
			bind:value={searchText}
			class="filter-input"
			aria-label="Search tasks"
		/>
	</div>

	<!-- Toggle control -->
	<div class="tree-toggle" role="group" aria-label="Tree display mode">
		<button
			class="toggle-btn"
			class:active={$taskTreeMode === 'tasks_only'}
			onclick={() => handleModeChange('tasks_only')}
		>
			TASKS ONLY
		</button>
		<button
			class="toggle-btn"
			class:active={$taskTreeMode === 'all_concepts'}
			onclick={() => handleModeChange('all_concepts')}
		>
			ALL CONCEPTS
		</button>
	</div>

	<!-- Tree -->
	{#if !$selectedCorpus}
		<div class="tree-empty">
			<span class="empty-heading">No corpus selected</span>
			<span class="empty-body">Select a corpus from the sidebar to view its task hierarchy.</span>
		</div>
	{:else if treeData.length === 0}
		<div class="tree-empty">
			<span class="empty-heading">No tasks discovered</span>
			<span class="empty-body">Run task discovery on a processed corpus to build the advocacy task hierarchy.</span>
		</div>
	{:else}
		<div class="tree-container" role="tree" aria-label="Task hierarchy tree">
			<Tree
				bind:this={treeRef}
				data={treeData}
				idMember="id"
				pathMember="path"
				displayValueMember="label"
				orderMember="sortOrder"
				levelMember="depth"
				searchValueMember="label"
				shouldUseInternalSearchIndex={true}
				bind:searchText={searchText}
				bind:selectedNode={selectedNode}
				dragDropMode="self"
				useFlatRendering={true}
				virtualScroll={true}
				virtualRowHeight={28}
				expandLevel={2}
				shouldToggleOnNodeClick={true}
				onNodeDrop={handleNodeDrop}
			>
				{#snippet nodeTemplate(node: LTreeNode<TaskTreeNode>)}
					{@const d = node.data}
					{#if d}
						<div
							class="tree-node-content"
							class:is-task={d.is_task}
							class:is-structural={!d.is_task}
							role="treeitem"
							aria-selected={node.isSelected}
							aria-expanded={node.hasChildren ? node.isExpanded : undefined}
						>
							<span class="node-label">{d.label}</span>

							{#if d.is_task}
								<span class="node-count">({d.unit_count})</span>

								<!-- Review indicator -->
								<span class="review-indicator" aria-label="Review status: {d.review_status}">
									{#if d.review_status === 'complete'}
										<svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
											<circle cx="4" cy="4" r="4" fill="var(--green)" />
										</svg>
									{:else if d.review_status === 'partial'}
										<svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
											<clipPath id="half-{d.id}">
												<rect x="0" y="0" width="4" height="8" />
											</clipPath>
											<circle cx="4" cy="4" r="3.5" fill="none" stroke="var(--surface3)" stroke-width="1" />
											<circle cx="4" cy="4" r="4" fill="var(--green)" clip-path="url(#half-{d.id})" />
										</svg>
									{:else}
										<svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
											<circle cx="4" cy="4" r="3" fill="none" stroke="var(--text-dim)" stroke-width="1" />
										</svg>
									{/if}
								</span>

								<!-- Flag icons -->
								<span class="flag-icons">
									{#if d.has_contradictions}
										<svg width="12" height="12" viewBox="0 0 12 12" style="color: var(--red)" aria-label="Has contradictions" role="img">
											<title>Has contradictions</title>
											<path d="M2 6h3M7 6h3M5 4l-1 2 1 2M7 4l1 2-1 2" fill="none" stroke="currentColor" stroke-width="1.5" />
										</svg>
									{/if}
									{#if d.has_orphans}
										<svg width="12" height="12" viewBox="0 0 12 12" style="color: var(--orange)" aria-label="Has orphan units" role="img">
											<title>Has orphan units</title>
											<circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" />
											<text x="6" y="8" text-anchor="middle" fill="currentColor" font-size="7" font-weight="600">?</text>
										</svg>
									{/if}
									{#if d.is_jurisdiction_sensitive}
										<svg width="12" height="12" viewBox="0 0 12 12" style="color: var(--orange)" aria-label="Jurisdiction-sensitive" role="img">
											<title>Jurisdiction-sensitive</title>
											<path d="M6 1L6 7M4.5 7a1.5 1.5 0 0 0 3 0" fill="none" stroke="currentColor" stroke-width="1.5" />
											<circle cx="6" cy="10" r="1" fill="currentColor" />
										</svg>
									{/if}
									{#if d.is_manual}
										<svg width="12" height="12" viewBox="0 0 12 12" style="color: var(--text-dim)" aria-label="Manually created" role="img">
											<title>Manually created</title>
											<path d="M2 10l5.5-5.5M8.5 3.5l1-1a.7.7 0 0 0-1-1l-1 1M6.5 9H10" fill="none" stroke="currentColor" stroke-width="1.5" />
										</svg>
									{/if}
									{#if d.is_procedural}
										<svg width="12" height="12" viewBox="0 0 12 12" style="color: var(--purple)" aria-label="Procedural task" role="img">
											<title>Procedural task</title>
											<text x="1" y="4" fill="currentColor" font-size="4" font-weight="600">1</text>
											<line x1="4" y1="3" x2="11" y2="3" stroke="currentColor" stroke-width="1" />
											<text x="1" y="8" fill="currentColor" font-size="4" font-weight="600">2</text>
											<line x1="4" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1" />
											<text x="1" y="12" fill="currentColor" font-size="4" font-weight="600">3</text>
											<line x1="4" y1="11" x2="11" y2="11" stroke="currentColor" stroke-width="1" />
										</svg>
									{/if}
								</span>
							{/if}
						</div>
					{/if}
				{/snippet}
			</Tree>
		</div>
	{/if}
</div>

<style>
	.task-tree {
		height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.tree-filter {
		padding: var(--sm);
		border-bottom: 1px solid var(--border);
	}

	.filter-input {
		width: 100%;
		padding: var(--xs) var(--sm);
		font-size: 14px;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
	}

	.filter-input::placeholder {
		color: var(--text-dim);
	}

	.tree-toggle {
		display: flex;
		padding: var(--sm);
		gap: 2px;
		border-bottom: 1px solid var(--border);
	}

	.toggle-btn {
		flex: 1;
		padding: var(--xs) var(--sm);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text-dim);
		transition: background 150ms, color 150ms;
	}

	.toggle-btn.active {
		background: var(--accent);
		color: #fff;
		border-color: var(--accent);
	}

	.tree-container {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
	}

	.tree-empty {
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

	.tree-node-content {
		display: flex;
		align-items: center;
		gap: var(--xs);
		height: 28px;
		font-size: 14px;
		font-weight: 400;
		cursor: pointer;
		user-select: none;
	}

	.tree-node-content.is-task {
		color: var(--text);
	}

	.tree-node-content.is-structural {
		color: var(--text-dim);
	}

	.node-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.node-count {
		font-size: 11px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.review-indicator {
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.flag-icons {
		display: flex;
		align-items: center;
		gap: var(--xs);
		flex-shrink: 0;
	}

	/* Override treeview library selected-node styling */
	:global(.task-tree .km-treeview--node-selected) {
		background: var(--highlight) !important;
		border-left: 2px solid var(--accent);
	}

	:global(.task-tree .km-treeview--node-selected .node-label) {
		color: var(--accent);
	}

	/* DnD drag active state */
	:global(.task-tree .km-treeview--node-dragging) {
		opacity: 0.6;
		outline: 1px dashed var(--accent);
	}

	/* DnD drop target state */
	:global(.task-tree .km-treeview--node-drag-over) {
		background: var(--highlight);
	}

	/* General treeview body styling */
	:global(.task-tree .km-treeview--body) {
		background: transparent;
		padding: var(--xs) 0;
	}

	:global(.task-tree .km-treeview--node) {
		padding: 0 var(--sm);
		min-height: 28px;
	}

	:global(.task-tree .km-treeview--node:hover) {
		background: var(--surface2);
	}
</style>
