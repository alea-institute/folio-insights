<script lang="ts">
	import {
		taskDetail,
		taskUnits,
		selectedUnitId,
		taskLoading,
		unitTypeFilter,
		confidenceBandFilter,
		reviewStatusFilter,
		flagFilter,
		contradictions,
		selectedContradictionId,
		submitTaskReview,
		taskAnnouncement,
	} from '$lib/stores/tasks';
	import { selectedCorpus } from '$lib/stores/corpus';
	import { bulkApproveTasks, type KnowledgeUnitResponse, type TaskUnitGroup } from '$lib/api/client';
	import ConfidenceBadge from './ConfidenceBadge.svelte';
	import ContradictionView from './ContradictionView.svelte';
	import FilterToolbar from './FilterToolbar.svelte';

	let expandedGroups = $state<Set<string>>(new Set(['best_practice', 'principle', 'pitfall', 'procedural_rule', 'citation']));

	const groupOrder = ['best_practice', 'principle', 'pitfall', 'procedural_rule', 'citation'];
	const groupLabels: Record<string, string> = {
		best_practice: 'Best Practices',
		principle: 'Principles',
		pitfall: 'Pitfalls',
		procedural_rule: 'Procedural Rules',
		citation: 'Citations',
	};

	function toggleGroup(type: string) {
		const s = new Set(expandedGroups);
		if (s.has(type)) {
			s.delete(type);
		} else {
			s.add(type);
		}
		expandedGroups = s;
	}

	function selectUnit(unit: KnowledgeUnitResponse) {
		$selectedUnitId = unit.id;
	}

	function copyIri(iri: string) {
		navigator.clipboard.writeText(iri);
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

	function confidenceBand(score: number): string {
		if (score >= 0.8) return 'high';
		if (score >= 0.5) return 'medium';
		return 'low';
	}

	// Filter units within each group based on active filters
	function filterUnits(units: KnowledgeUnitResponse[]): KnowledgeUnitResponse[] {
		let filtered = units;

		// Confidence band
		const confBand = $confidenceBandFilter;
		if (confBand !== 'all') {
			filtered = filtered.filter((u) => confidenceBand(u.confidence) === confBand);
		}

		// Review status
		const reviewStatus = $reviewStatusFilter;
		if (reviewStatus !== 'all') {
			filtered = filtered.filter((u) => u.review_status === reviewStatus);
		}

		return filtered;
	}

	// Filter groups based on type filter
	function filteredGroups(groups: TaskUnitGroup[]): TaskUnitGroup[] {
		const typeFilter = $unitTypeFilter;
		let result = groups;

		if (typeFilter.length > 0) {
			result = result.filter((g) => typeFilter.includes(g.type));
		}

		// Sort by group order
		return result.sort(
			(a, b) => groupOrder.indexOf(a.type) - groupOrder.indexOf(b.type)
		);
	}

	let displayGroups = $derived(filteredGroups($taskUnits));

	// Check if any active contradiction
	let activeContradiction = $derived(
		$contradictions.find((c) => c.id === $selectedContradictionId)
	);

	async function approveGroupHigh(type: string) {
		const corpus = $selectedCorpus;
		if (!corpus) return;
		const group = $taskUnits.find((g) => g.type === type);
		if (!group) return;
		const highIds = group.units
			.filter((u) => u.confidence >= 0.8 && u.review_status !== 'approved')
			.map((u) => u.id);
		if (highIds.length === 0) return;
		// Use bulk approve with specific IDs
		await bulkApproveTasks(corpus.id, highIds);
		$taskAnnouncement = `Approved ${highIds.length} high-confidence units`;
	}
</script>

<div class="task-detail">
	{#if !$taskDetail}
		<div class="empty-state">
			<span class="empty-heading">No task selected</span>
			<span class="empty-body">Select a task from the tree to view its knowledge units and review status.</span>
		</div>
	{:else if $taskLoading}
		<div class="loading">Loading task detail...</div>
	{:else}
		<!-- Task Header -->
		<div class="task-header">
			<h2 class="task-label">{$taskDetail.label}</h2>
			<div class="task-iri">
				<code>{$taskDetail.folio_iri}</code>
				<button
					class="copy-btn"
					onclick={() => copyIri($taskDetail?.folio_iri ?? '')}
					aria-label="Copy IRI"
					title="Copy IRI"
				>
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<rect x="9" y="9" width="13" height="13" rx="2" />
						<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
					</svg>
				</button>
			</div>
			<div class="task-meta">
				{#if $taskDetail.is_procedural}
					<span class="type-badge type-procedural">PROCEDURAL</span>
				{:else}
					<span class="type-badge type-categorical">CATEGORICAL</span>
				{/if}
				<ConfidenceBadge score={$taskDetail.confidence} />
			</div>
		</div>

		<!-- Filter Toolbar -->
		<FilterToolbar />

		<!-- Contradiction View (if active) -->
		{#if activeContradiction}
			<ContradictionView contradiction={activeContradiction} />
		{/if}

		<!-- Unit Type Groups -->
		<div class="unit-groups" role="list">
			{#each displayGroups as group (group.type)}
				{@const filtered = filterUnits(group.units)}
				{@const isExpanded = expandedGroups.has(group.type)}
				<div class="unit-group">
					<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
					<div
						class="group-header"
						role="heading"
						aria-level={3}
						onclick={() => toggleGroup(group.type)}
						onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleGroup(group.type); } }}
						tabindex="0"
					>
						<span class="group-chevron">
							{#if isExpanded}
								<svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
							{:else}
								<svg width="12" height="12" viewBox="0 0 12 12"><path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
							{/if}
						</span>
						<span class="group-label">{groupLabels[group.type] ?? group.type}</span>
						<span class="group-count">({filtered.length})</span>
						<button
							class="approve-all-btn"
							onclick={(e) => { e.stopPropagation(); approveGroupHigh(group.type); }}
							title="Approve all high-confidence units in this group"
						>
							Approve All
						</button>
					</div>

					{#if isExpanded}
						<div class="group-units">
							{#if filtered.length === 0}
								<div class="no-units">No units match the current filters.</div>
							{:else}
								{#each filtered as unit (unit.id)}
									{@const isSelected = $selectedUnitId === unit.id}
									{@const hasContradiction = $contradictions.some(
										(c) => c.unit_id_a === unit.id || c.unit_id_b === unit.id
									)}
									<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
									<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
									<div
										class="unit-card"
										class:selected={isSelected}
										class:has-contradiction={hasContradiction}
										role="listitem"
										style:background={unitBg(unit.review_status)}
										onclick={() => selectUnit(unit)}
										onkeydown={(e) => { if (e.key === 'Enter') selectUnit(unit); }}
										tabindex="0"
									>
										<div class="status-dot" style:background={statusDotColor(unit.review_status)}></div>
										<div class="unit-content">
											<p class="unit-text">
												{#if unit.review_status === 'edited' && unit.edited_text}
													{unit.edited_text}
												{:else}
													{unit.text}
												{/if}
											</p>
											<div class="unit-meta">
												<span class="unit-type-tag">{unit.unit_type}</span>
												<ConfidenceBadge score={unit.confidence} />
												{#each unit.folio_tags as tag}
													<span class="path-badge">{tag.extraction_path}</span>
												{/each}
											</div>
										</div>
									</div>
								{/each}
							{/if}
						</div>
					{/if}
				</div>
			{/each}

			{#if displayGroups.length === 0 && $taskUnits.length === 0}
				<div class="empty-state">
					<span class="empty-body">No knowledge units assigned to this task.</span>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.task-detail {
		height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.task-header {
		padding: var(--md);
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.task-label {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.3px;
	}

	.task-iri {
		display: flex;
		align-items: center;
		gap: var(--xs);
		margin-top: var(--xs);
	}

	.task-iri code {
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

	.task-meta {
		display: flex;
		align-items: center;
		gap: var(--sm);
		margin-top: var(--sm);
	}

	.type-badge {
		padding: 1px 8px;
		border-radius: 9999px;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-weight: 600;
	}

	.type-procedural {
		background: rgba(176, 126, 232, 0.15);
		color: var(--purple);
	}

	.type-categorical {
		background: var(--surface3);
		color: var(--text-dim);
	}

	.unit-groups {
		flex: 1;
		overflow-y: auto;
		padding: var(--sm);
	}

	.unit-group {
		margin-bottom: var(--sm);
	}

	.group-header {
		display: flex;
		align-items: center;
		gap: var(--xs);
		padding: var(--xs) var(--sm);
		cursor: pointer;
		user-select: none;
		border-radius: 4px;
		transition: background 100ms;
	}

	.group-header:hover {
		background: var(--surface2);
	}

	.group-header:hover .approve-all-btn {
		opacity: 1;
	}

	.group-chevron {
		display: flex;
		align-items: center;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.group-label {
		font-size: 14px;
		font-weight: 600;
	}

	.group-count {
		font-size: 11px;
		color: var(--text-dim);
	}

	.approve-all-btn {
		margin-left: auto;
		font-size: 11px;
		color: var(--green);
		opacity: 0;
		transition: opacity 150ms;
		padding: 2px 6px;
		border-radius: 3px;
	}

	.approve-all-btn:hover {
		background: rgba(76, 175, 124, 0.15);
	}

	.group-units {
		padding-left: var(--md);
		display: flex;
		flex-direction: column;
		gap: var(--sm);
		margin-top: var(--xs);
	}

	.no-units {
		font-size: 14px;
		color: var(--text-dim);
		padding: var(--sm);
	}

	.unit-card {
		display: flex;
		gap: var(--sm);
		padding: var(--sm);
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 6px;
		cursor: pointer;
		transition: border-color 150ms;
	}

	.unit-card:hover {
		border-color: var(--accent-dim);
	}

	.unit-card.selected {
		border-color: var(--accent);
	}

	.unit-card.has-contradiction {
		border-left: 2px solid var(--red);
		background: var(--contradiction);
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
	}

	.unit-type-tag {
		padding: 1px 6px;
		background: var(--surface3);
		border-radius: 3px;
		color: var(--text-dim);
		text-transform: uppercase;
		font-size: 10px;
		letter-spacing: 0.5px;
	}

	.path-badge {
		padding: 1px 6px;
		border-radius: 9999px;
		font-size: 11px;
		background: var(--surface3);
		color: var(--text-dim);
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

	.loading {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--text-dim);
		font-size: 14px;
	}
</style>
