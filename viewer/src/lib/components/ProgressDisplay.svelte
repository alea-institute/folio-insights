<script lang="ts">
	let {
		progress,
		currentStage,
		status,
	}: {
		progress: number;
		currentStage: string;
		status: 'idle' | 'processing' | 'complete' | 'error';
	} = $props();

	const STAGES = [
		{ key: 'ingestion', label: 'Ingestion' },
		{ key: 'structure_parser', label: 'Structure' },
		{ key: 'boundary_detection', label: 'Boundaries' },
		{ key: 'distiller', label: 'Distillation' },
		{ key: 'knowledge_classifier', label: 'Classification' },
		{ key: 'folio_tagger', label: 'FOLIO Tagging' },
		{ key: 'deduplicator', label: 'Deduplication' },
	];

	function stageState(
		stageKey: string
	): 'pending' | 'active' | 'complete' | 'error' {
		if (status === 'complete') return 'complete';
		if (status === 'idle') return 'pending';

		const currentIdx = STAGES.findIndex((s) => s.key === currentStage);
		const thisIdx = STAGES.findIndex((s) => s.key === stageKey);

		if (currentIdx < 0) return 'pending';
		if (thisIdx < currentIdx) return 'complete';
		if (thisIdx === currentIdx) return status === 'error' ? 'error' : 'active';
		return 'pending';
	}

	let barColor = $derived(
		status === 'complete'
			? 'var(--green)'
			: status === 'error'
				? 'var(--red)'
				: 'var(--accent)'
	);
</script>

<div class="progress-display">
	<div
		class="progress-track"
		role="progressbar"
		aria-valuenow={progress}
		aria-valuemin={0}
		aria-valuemax={100}
		aria-label="Pipeline processing progress"
	>
		<div
			class="progress-fill"
			style="width: {progress}%; background: {barColor}"
		></div>
	</div>

	<div class="stage-pills">
		{#each STAGES as stage}
			{@const state = stageState(stage.key)}
			<span
				class="pill {state}"
				aria-current={state === 'active' ? 'step' : undefined}
			>
				{stage.label}
			</span>
		{/each}
	</div>
</div>

<style>
	.progress-display {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
	}

	.progress-track {
		height: 3px;
		background: var(--surface3);
		border-radius: 2px;
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		border-radius: 2px;
		transition: width 0.3s ease;
	}

	.stage-pills {
		display: flex;
		flex-wrap: wrap;
		gap: var(--xs);
	}

	.pill {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: var(--xs) var(--sm);
		border-radius: 3px;
		transition: background 150ms ease, color 150ms ease;
		white-space: nowrap;
	}

	.pill.pending {
		background: var(--surface2);
		color: var(--text-dim);
	}

	.pill.active {
		background: rgba(108, 140, 255, 0.2);
		color: var(--accent);
	}

	.pill.complete {
		background: rgba(76, 175, 124, 0.2);
		color: var(--green);
	}

	.pill.error {
		background: rgba(224, 85, 85, 0.2);
		color: var(--red);
	}
</style>
