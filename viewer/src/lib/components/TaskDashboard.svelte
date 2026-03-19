<script lang="ts">
	import type { DiscoveryStatsResponse } from '$lib/api/client';

	let {
		stats,
		visible,
		onclose,
	}: {
		stats: DiscoveryStatsResponse;
		visible: boolean;
		onclose: () => void;
	} = $props();

	let topLevel = $derived(stats.total_tasks - stats.total_subtasks);
	let pendingContradictions = $derived(stats.contradiction_count - stats.contradictions_resolved);

	let totalSources = $derived(
		Object.values(stats.source_coverage).reduce((a, b) => a + b, 0)
	);
	let coveredSources = $derived(
		Object.keys(stats.source_coverage).length
	);

	let highCount = $derived(stats.by_confidence['high'] ?? 0);
	let mediumCount = $derived(stats.by_confidence['medium'] ?? 0);
	let lowCount = $derived(stats.by_confidence['low'] ?? 0);
	let totalConfidence = $derived(highCount + mediumCount + lowCount);

	let avgConfidenceLabel = $derived(
		totalConfidence === 0
			? 'N/A'
			: highCount >= mediumCount && highCount >= lowCount
				? 'High'
				: mediumCount >= lowCount
					? 'Medium'
					: 'Low'
	);

	let avgConfidenceColor = $derived(
		avgConfidenceLabel === 'High'
			? 'var(--green)'
			: avgConfidenceLabel === 'Medium'
				? 'var(--orange)'
				: avgConfidenceLabel === 'Low'
					? 'var(--red)'
					: 'var(--text-dim)'
	);

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			onclose();
		}
	}
</script>

{#if visible}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="dashboard-overlay" role="dialog" aria-label="Task summary dashboard" onkeydown={handleKeydown}>
		<div class="dashboard-header">
			<h3 class="dashboard-title">Task Summary</h3>
			<button class="close-btn" onclick={onclose} aria-label="Close dashboard">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M18 6L6 18M6 6l12 12" />
				</svg>
			</button>
		</div>
		<div class="stat-grid">
			<!-- Total Tasks -->
			<div class="stat-card">
				<span class="stat-label">TASKS</span>
				<span class="stat-value" style="color: var(--text)">{stats.total_tasks}</span>
				<span class="stat-sub">{topLevel} top-level, {stats.total_subtasks} subtasks</span>
			</div>

			<!-- Knowledge Units -->
			<div class="stat-card">
				<span class="stat-label">UNITS ASSIGNED</span>
				<span class="stat-value" style="color: var(--text)">{stats.total_units_assigned}</span>
				<span class="stat-sub" class:orphan-warn={stats.orphan_count > 0}>
					{stats.orphan_count} orphans remaining
				</span>
			</div>

			<!-- Review Progress -->
			<div class="stat-card">
				<span class="stat-label">REVIEW PROGRESS</span>
				<span class="stat-value" style="color: var(--green)">{stats.review_progress_pct}%</span>
				<span class="stat-sub">{stats.review_progress_pct}% complete</span>
			</div>

			<!-- Contradictions -->
			<div class="stat-card">
				<span class="stat-label">CONTRADICTIONS</span>
				<span class="stat-value" style="color: {pendingContradictions > 0 ? 'var(--red)' : 'var(--green)'}">
					{stats.contradiction_count}
				</span>
				<span class="stat-sub">{stats.contradictions_resolved} resolved, {pendingContradictions} pending</span>
			</div>

			<!-- Source Coverage -->
			<div class="stat-card">
				<span class="stat-label">SOURCE COVERAGE</span>
				<span class="stat-value" style="color: var(--text)">{coveredSources}/{totalSources}</span>
				<span class="stat-sub">{coveredSources}/{totalSources} files represented</span>
			</div>

			<!-- Confidence -->
			<div class="stat-card">
				<span class="stat-label">AVG CONFIDENCE</span>
				<span class="stat-value" style="color: {avgConfidenceColor}">{avgConfidenceLabel}</span>
				<div class="confidence-bar">
					{#if totalConfidence > 0}
						<div class="bar-segment bar-high" style="width: {(highCount / totalConfidence) * 100}%"></div>
						<div class="bar-segment bar-medium" style="width: {(mediumCount / totalConfidence) * 100}%"></div>
						<div class="bar-segment bar-low" style="width: {(lowCount / totalConfidence) * 100}%"></div>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

<style>
	.dashboard-overlay {
		position: absolute;
		top: 56px;
		right: var(--md);
		width: 480px;
		max-height: 70vh;
		overflow-y: auto;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
		z-index: 100;
		padding: var(--md);
	}

	.dashboard-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--md);
	}

	.dashboard-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--text);
	}

	.close-btn {
		color: var(--text-dim);
		display: flex;
		align-items: center;
	}

	.close-btn:hover {
		color: var(--text);
	}

	.stat-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--md);
	}

	.stat-card {
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: var(--md);
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.stat-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-dim);
	}

	.stat-value {
		font-size: 28px;
		font-weight: 600;
		line-height: 1.2;
	}

	.stat-sub {
		font-size: 11px;
		color: var(--text-dim);
	}

	.orphan-warn {
		color: var(--orange);
	}

	.confidence-bar {
		display: flex;
		height: 4px;
		border-radius: 2px;
		overflow: hidden;
		margin-top: var(--xs);
	}

	.bar-segment {
		height: 100%;
	}

	.bar-high {
		background: var(--green);
	}

	.bar-medium {
		background: var(--orange);
	}

	.bar-low {
		background: var(--red);
	}
</style>
