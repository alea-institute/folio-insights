<script lang="ts">
	import { taskDetail, selectedTaskId } from '$lib/stores/tasks';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let activeSignals = $state<Set<string>>(new Set(['heading', 'clustering', 'llm']));

	function toggleSignal(signal: string) {
		const s = new Set(activeSignals);
		if (s.has(signal)) {
			s.delete(signal);
		} else {
			s.add(signal);
		}
		activeSignals = s;
	}

	// Placeholder evidence data structure -- will be populated from API
	// when discovery evidence endpoint is available
	interface HeadingSignal {
		breadcrumb: string;
		confidence: number;
	}

	interface ClusterSignal {
		cluster_id: string;
		distance: number;
		co_clustered: string[];
	}

	interface LlmSignal {
		suggested_label: string;
		reasoning: string;
	}

	// These would come from a future discovery evidence API endpoint
	let headingSignal = $state<HeadingSignal | null>(null);
	let clusterSignal = $state<ClusterSignal | null>(null);
	let llmSignal = $state<LlmSignal | null>(null);
	let showAllClustered = $state(false);

	// Reset evidence when task changes
	$effect(() => {
		const _taskId = $selectedTaskId;
		headingSignal = null;
		clusterSignal = null;
		llmSignal = null;
		showAllClustered = false;
	});
</script>

<div class="discovery-evidence">
	<div class="evidence-header">
		<span class="evidence-title">Discovery Evidence</span>
		<div class="signal-toggles">
			<button
				class="signal-pill"
				class:active={activeSignals.has('heading')}
				onclick={() => toggleSignal('heading')}
			>
				Heading
			</button>
			<button
				class="signal-pill"
				class:active={activeSignals.has('clustering')}
				onclick={() => toggleSignal('clustering')}
			>
				Clustering
			</button>
			<button
				class="signal-pill"
				class:active={activeSignals.has('llm')}
				onclick={() => toggleSignal('llm')}
			>
				LLM
			</button>
		</div>
	</div>

	{#if !$selectedTaskId}
		<div class="evidence-empty">
			<span>Select a task to view its discovery evidence.</span>
		</div>
	{:else}
		<div class="evidence-content">
			<!-- Heading Signal -->
			{#if activeSignals.has('heading')}
				<div class="evidence-section heading-section">
					<div class="section-title">Heading Signal</div>
					{#if headingSignal}
						<div class="breadcrumb-path">{headingSignal.breadcrumb}</div>
						<div class="signal-meta">
							<ConfidenceBadge score={headingSignal.confidence} />
						</div>
					{:else}
						<div class="no-signal">No heading signal data available for this task.</div>
					{/if}
				</div>
			{/if}

			<!-- Clustering Signal -->
			{#if activeSignals.has('clustering')}
				<div class="evidence-section cluster-section">
					<div class="section-title">Clustering Signal</div>
					{#if clusterSignal}
						<div class="cluster-meta">
							<span class="cluster-id">Cluster: {clusterSignal.cluster_id}</span>
							<span class="cluster-distance">Distance: {clusterSignal.distance.toFixed(3)}</span>
						</div>
						<div class="co-clustered">
							{#each (showAllClustered ? clusterSignal.co_clustered : clusterSignal.co_clustered.slice(0, 5)) as unit}
								<div class="clustered-unit">{unit}</div>
							{/each}
							{#if clusterSignal.co_clustered.length > 5 && !showAllClustered}
								<button class="show-more" onclick={() => (showAllClustered = true)}>
									Show {clusterSignal.co_clustered.length - 5} more
								</button>
							{/if}
						</div>
					{:else}
						<div class="no-signal">No clustering signal data available for this task.</div>
					{/if}
				</div>
			{/if}

			<!-- LLM Signal -->
			{#if activeSignals.has('llm')}
				<div class="evidence-section llm-section">
					<div class="section-title">LLM Signal</div>
					{#if llmSignal}
						<div class="llm-label">{llmSignal.suggested_label}</div>
						<div class="llm-reasoning">{llmSignal.reasoning}</div>
					{:else}
						<div class="no-signal">No LLM signal data available for this task.</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.discovery-evidence {
		height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.evidence-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sm);
		padding: var(--sm) var(--md);
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.evidence-title {
		font-size: 14px;
		font-weight: 600;
	}

	.signal-toggles {
		display: flex;
		gap: 2px;
	}

	.signal-pill {
		padding: var(--xs) var(--sm);
		font-size: 11px;
		border-radius: 9999px;
		background: var(--surface2);
		color: var(--text-dim);
		transition: background 150ms, color 150ms;
	}

	.signal-pill:hover {
		color: var(--text);
	}

	.signal-pill.active {
		background: var(--highlight);
		color: var(--accent);
	}

	.evidence-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--text-dim);
		font-size: 14px;
		padding: var(--lg);
	}

	.evidence-content {
		flex: 1;
		overflow-y: auto;
	}

	.evidence-section {
		padding: var(--sm) var(--md);
		border-bottom: 1px solid var(--border);
	}

	.heading-section {
		background: var(--discovery-heading);
	}

	.cluster-section {
		background: var(--discovery-cluster);
	}

	.llm-section {
		background: var(--discovery-llm);
	}

	.section-title {
		font-size: 14px;
		font-weight: 600;
		margin-bottom: var(--xs);
	}

	.breadcrumb-path {
		font-size: 11px;
		color: var(--text-dim);
		margin-bottom: var(--xs);
	}

	.signal-meta {
		display: flex;
		align-items: center;
		gap: var(--xs);
	}

	.cluster-meta {
		display: flex;
		gap: var(--sm);
		font-size: 11px;
		color: var(--text-dim);
		margin-bottom: var(--xs);
	}

	.cluster-id,
	.cluster-distance {
		font-family: monospace;
	}

	.co-clustered {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.clustered-unit {
		font-size: 14px;
		line-height: 1.4;
		padding: 2px 0;
	}

	.show-more {
		font-size: 11px;
		color: var(--accent);
		padding: var(--xs) 0;
	}

	.llm-label {
		font-size: 14px;
		font-weight: 600;
		margin-bottom: var(--xs);
	}

	.llm-reasoning {
		font-size: 14px;
		line-height: 1.5;
		color: var(--text);
	}

	.no-signal {
		font-size: 14px;
		color: var(--text-dim);
		font-style: italic;
	}
</style>
