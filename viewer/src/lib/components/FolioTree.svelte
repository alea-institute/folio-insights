<script lang="ts">
	import { treeData, selectedConcept, filterText } from '$lib/stores/tree';
	import { loadUnits } from '$lib/stores/review';
	import type { TreeNode } from '$lib/api/client';

	let { onselectconcept }: { onselectconcept?: (node: TreeNode) => void } = $props();

	let expandedNodes = $state<Set<string>>(new Set());

	function toggleNode(node: TreeNode) {
		const s = new Set(expandedNodes);
		if (s.has(node.label)) {
			s.delete(node.label);
		} else {
			s.add(node.label);
		}
		expandedNodes = s;
	}

	function selectNode(node: TreeNode) {
		if (node.iri) {
			$selectedConcept = node;
			onselectconcept?.(node);
		}
	}

	function handleBranchClick(branch: TreeNode) {
		// Leaf branches (like "All Units", "Untagged") are directly selectable
		const isLeaf = branch.iri && branch.children.length === 0;
		if (!isLeaf) {
			toggleNode(branch);
		}
		selectNode(branch);
	}

	function handleKeydown(e: KeyboardEvent, node: TreeNode) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			if (node.children.length > 0) {
				toggleNode(node);
			}
			selectNode(node);
		}
	}

	function matchesFilter(node: TreeNode, filter: string): boolean {
		const lower = filter.toLowerCase();
		if (node.label.toLowerCase().includes(lower)) return true;
		return node.children.some((c) => matchesFilter(c, lower));
	}

	function filteredTree(nodes: TreeNode[], filter: string): TreeNode[] {
		if (!filter) return nodes;
		return nodes
			.filter((n) => matchesFilter(n, filter))
			.map((n) => ({
				...n,
				children: filteredTree(n.children, filter),
			}));
	}

	let visibleTree = $derived(filteredTree($treeData, $filterText));
</script>

<div class="folio-tree">
	<div class="tree-filter">
		<input
			type="text"
			placeholder="Filter concepts..."
			bind:value={$filterText}
			class="filter-input"
			aria-label="Filter concepts"
		/>
	</div>

	{#if visibleTree.length === 0}
		<div class="tree-empty">No concepts match your filter</div>
	{:else}
		<div role="tree" aria-label="FOLIO concept tree">
			{#each visibleTree as branch}
				{@const isExpanded = expandedNodes.has(branch.label)}
				{@const isBranchSelected = $selectedConcept?.iri === branch.iri}
				{@const isLeafBranch = !!branch.iri && branch.children.length === 0}
				<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
				<div
					role="treeitem"
					aria-expanded={isLeafBranch ? undefined : isExpanded}
					aria-selected={isBranchSelected}
					class="tree-node branch-node"
					class:expanded={isExpanded}
					class:selected={isBranchSelected}
					class:leaf-branch={isLeafBranch}
					onclick={() => handleBranchClick(branch)}
					onkeydown={(e) => handleKeydown(e, branch)}
					tabindex="0"
				>
					{#if !isLeafBranch}
					<span class="chevron">
						{#if isExpanded}
							<svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
						{:else}
							<svg width="12" height="12" viewBox="0 0 12 12"><path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
						{/if}
					</span>
					{:else}
					<span class="leaf-icon">
						<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="2.5" fill="currentColor" opacity="0.4"/></svg>
					</span>
					{/if}
					<span class="node-label">{branch.label}</span>
					<span class="node-count">{branch.unit_count}</span>
				</div>

				{#if isExpanded && branch.children.length > 0}
					<div role="group" class="tree-children">
						{#each branch.children as child}
							{@const isSelected = $selectedConcept?.iri === child.iri}
							<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
							<div
								role="treeitem"
								aria-selected={isSelected}
								class="tree-node child-node"
								class:selected={isSelected}
								onclick={() => selectNode(child)}
								onkeydown={(e) => handleKeydown(e, child)}
								tabindex="0"
							>
								<span class="node-label">{child.label}</span>
								<span class="node-count">{child.unit_count}</span>
							</div>
						{/each}
					</div>
				{/if}
			{/each}
		</div>
	{/if}
</div>

<style>
	.folio-tree {
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

	.tree-empty {
		padding: var(--lg);
		color: var(--text-dim);
		font-size: 13px;
		text-align: center;
	}

	[role="tree"] {
		flex: 1;
		overflow-y: auto;
		padding: var(--xs) 0;
	}

	.tree-node {
		display: flex;
		align-items: center;
		height: 28px;
		padding: 0 var(--sm);
		font-size: 13px;
		cursor: pointer;
		user-select: none;
		transition: background 100ms;
	}

	.tree-node:hover {
		background: var(--surface2);
	}

	.tree-node.selected {
		background: var(--highlight);
		color: var(--accent);
		border-left: 2px solid var(--accent);
	}

	.branch-node {
		font-weight: 500;
	}

	.child-node {
		padding-left: calc(var(--md) + var(--sm));
	}

	.chevron {
		display: flex;
		align-items: center;
		width: 16px;
		flex-shrink: 0;
		color: var(--text-dim);
	}

	.leaf-icon {
		display: flex;
		align-items: center;
		width: 16px;
		flex-shrink: 0;
		color: var(--accent);
	}

	.node-label {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.node-count {
		font-size: 11px;
		color: var(--text-dim);
		margin-left: var(--sm);
		flex-shrink: 0;
	}

	.tree-children {
		/* Slide animation for expand/collapse */
		overflow: hidden;
		animation: slideDown 150ms ease-out;
	}

	@keyframes slideDown {
		from { max-height: 0; opacity: 0; }
		to { max-height: 500px; opacity: 1; }
	}
</style>
