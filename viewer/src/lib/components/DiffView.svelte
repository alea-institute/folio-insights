<script lang="ts">
	let {
		changes,
		onaccept,
		onreject,
		onacceptall,
		onrejectall,
	}: {
		changes: Array<{ type: 'added' | 'removed' | 'changed'; description: string; id: string }>;
		onaccept: (id: string) => void;
		onreject: (id: string) => void;
		onacceptall: () => void;
		onrejectall: () => void;
	} = $props();

	function typeIcon(type: 'added' | 'removed' | 'changed'): string {
		if (type === 'added') return '+';
		if (type === 'removed') return '\u2212';
		return '~';
	}

	function typeBg(type: 'added' | 'removed' | 'changed'): string {
		if (type === 'added') return 'var(--diff-added)';
		if (type === 'removed') return 'var(--diff-removed)';
		return 'var(--diff-changed)';
	}

	function typeColor(type: 'added' | 'removed' | 'changed'): string {
		if (type === 'added') return 'var(--green)';
		if (type === 'removed') return 'var(--red)';
		return 'var(--orange)';
	}
</script>

<div class="diff-view">
	<div class="diff-header">
		<h3 class="diff-title">Changes detected from re-run. Review and accept or reject each change.</h3>
		<div class="bulk-actions">
			<button class="btn-outline btn-accept-all" onclick={onacceptall}>
				Accept All Changes
			</button>
			<button class="btn-outline btn-reject-all" onclick={onrejectall}>
				Reject All Changes
			</button>
		</div>
	</div>

	{#if changes.length === 0}
		<p class="no-changes">No changes detected.</p>
	{:else}
		<div class="change-list">
			{#each changes as change (change.id)}
				<div class="change-row" style="background: {typeBg(change.type)}">
					<span class="change-icon" style="color: {typeColor(change.type)}">
						{typeIcon(change.type)}
					</span>
					<span class="change-desc">{change.description}</span>
					<div class="change-actions">
						<button
							class="btn-outline btn-accept"
							onclick={() => onaccept(change.id)}
						>
							Accept Change
						</button>
						<button
							class="btn-outline btn-reject"
							onclick={() => onreject(change.id)}
						>
							Reject Change
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.diff-view {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
	}

	.diff-header {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
	}

	.diff-title {
		font-size: 14px;
		font-weight: 400;
		color: var(--text-dim);
		line-height: 1.5;
	}

	.bulk-actions {
		display: flex;
		gap: var(--sm);
	}

	.btn-outline {
		padding: var(--xs) var(--sm);
		font-size: 11px;
		font-weight: 600;
		border-radius: 4px;
		background: transparent;
		cursor: pointer;
		transition: opacity 150ms ease;
	}

	.btn-outline:hover {
		opacity: 0.8;
	}

	.btn-accept-all,
	.btn-accept {
		border: 1px solid var(--green);
		color: var(--green);
	}

	.btn-reject-all,
	.btn-reject {
		border: 1px solid var(--red);
		color: var(--red);
	}

	.no-changes {
		font-size: 14px;
		color: var(--text-dim);
		padding: var(--md) 0;
	}

	.change-list {
		display: flex;
		flex-direction: column;
		gap: var(--xs);
	}

	.change-row {
		display: flex;
		align-items: center;
		gap: var(--sm);
		padding: var(--sm) var(--md);
		border-radius: 4px;
	}

	.change-icon {
		font-size: 18px;
		font-weight: 600;
		flex-shrink: 0;
		width: 20px;
		text-align: center;
	}

	.change-desc {
		flex: 1;
		font-size: 14px;
		color: var(--text);
	}

	.change-actions {
		display: flex;
		gap: var(--xs);
		flex-shrink: 0;
	}
</style>
