<script lang="ts">
	let {
		entries,
		expanded = false,
	}: {
		entries: Array<{ timestamp: string; stage: string; message: string }>;
		expanded?: boolean;
	} = $props();

	let isExpanded = $state(false);
	let logContainer: HTMLDivElement;

	// Sync with prop changes (e.g. auto-expand on error)
	$effect(() => {
		if (expanded) isExpanded = true;
	});

	// Auto-scroll to bottom when new entries arrive
	$effect(() => {
		if (entries.length && logContainer && isExpanded) {
			logContainer.scrollTop = logContainer.scrollHeight;
		}
	});

	function formatTime(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleTimeString('en-US', {
				hour12: false,
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return iso;
		}
	}

	const STAGE_COLORS: Record<string, string> = {
		ingestion: 'var(--accent)',
		structure_parser: 'var(--accent)',
		boundary_detection: 'var(--accent)',
		distiller: 'var(--accent)',
		knowledge_classifier: 'var(--accent)',
		folio_tagger: 'var(--accent)',
		deduplicator: 'var(--accent)',
	};

	function stageColor(stage: string): string {
		return STAGE_COLORS[stage] ?? 'var(--text-dim)';
	}
</script>

<div class="activity-log">
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="log-toggle"
		onclick={() => (isExpanded = !isExpanded)}
		onkeydown={(e) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				isExpanded = !isExpanded;
			}
		}}
		role="button"
		tabindex="0"
		aria-expanded={isExpanded}
		aria-controls="activity-log-content"
	>
		<svg
			class="chevron"
			class:expanded={isExpanded}
			width="12"
			height="12"
			viewBox="0 0 12 12"
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
		>
			<path d="M2 4l4 4 4-4" />
		</svg>
		<span>Activity Log</span>
		{#if entries.length > 0}
			<span class="entry-count">({entries.length})</span>
		{/if}
	</div>

	<div
		id="activity-log-content"
		class="log-content"
		class:collapsed={!isExpanded}
		bind:this={logContainer}
	>
		{#each entries as entry}
			<div class="log-entry">
				<span class="log-time">{formatTime(entry.timestamp)}</span>
				<span class="log-stage" style="color: {stageColor(entry.stage)}">
					{entry.stage}
				</span>
				<span class="log-message">{entry.message}</span>
			</div>
		{/each}
		{#if entries.length === 0}
			<div class="log-empty">No activity yet</div>
		{/if}
	</div>
</div>

<style>
	.activity-log {
		border: 1px solid var(--border);
		border-radius: 4px;
		overflow: hidden;
	}

	.log-toggle {
		display: flex;
		align-items: center;
		gap: var(--xs);
		padding: var(--xs) var(--sm);
		cursor: pointer;
		user-select: none;
		font-size: 11px;
		color: var(--text-dim);
		transition: color 150ms ease;
	}

	.log-toggle:hover {
		color: var(--text);
	}

	.chevron {
		transition: transform 0.15s ease;
		transform: rotate(-90deg);
		flex-shrink: 0;
	}

	.chevron.expanded {
		transform: rotate(0deg);
	}

	.entry-count {
		color: var(--text-dim);
		font-size: 11px;
	}

	.log-content {
		max-height: 240px;
		overflow-y: auto;
		padding: 0 var(--sm) var(--xs);
		transition: max-height 150ms ease-out, opacity 150ms ease-out;
	}

	.log-content.collapsed {
		max-height: 0;
		opacity: 0;
		overflow: hidden;
		padding: 0 var(--sm);
	}

	.log-entry {
		display: flex;
		align-items: baseline;
		gap: var(--xs);
		padding: var(--xs) 0;
		font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
		font-size: 11px;
		line-height: 1.4;
	}

	.log-time {
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.log-stage {
		font-weight: 600;
		flex-shrink: 0;
		min-width: 80px;
	}

	.log-message {
		color: var(--text);
	}

	.log-empty {
		font-size: 11px;
		color: var(--text-dim);
		padding: var(--xs) 0;
	}
</style>
