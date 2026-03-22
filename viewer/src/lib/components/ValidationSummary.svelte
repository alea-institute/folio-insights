<script lang="ts">
	import type { ExportValidationCheck } from '$lib/api/client';

	let { checks }: { checks: ExportValidationCheck[] } = $props();

	function badgeClass(status: string): string {
		if (status === 'PASS') return 'badge-pass';
		if (status === 'WARN') return 'badge-warn';
		return 'badge-fail';
	}

	function ariaLabel(check: ExportValidationCheck): string {
		const verb = check.status === 'PASS' ? 'passed' : check.status === 'WARN' ? 'warned' : 'failed';
		return `${check.name} validation: ${verb}`;
	}
</script>

<div class="validation-container">
	<h4 class="validation-title">Validation Results</h4>
	{#each checks as check}
		<div class="check-row">
			<span
				class="badge {badgeClass(check.status)}"
				aria-label={ariaLabel(check)}
			>
				{check.status}
			</span>
			<span class="check-name">{check.name}</span>
			{#if check.details}
				<span class="check-details">{check.details}</span>
			{/if}
		</div>
	{/each}
</div>

<style>
	.validation-container {
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: var(--sm);
		opacity: 0;
		animation: fadeIn 150ms ease forwards;
	}

	@keyframes fadeIn {
		to {
			opacity: 1;
		}
	}

	.validation-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: var(--sm);
	}

	.check-row {
		display: flex;
		align-items: center;
		gap: var(--sm);
		padding: 4px 0;
	}

	.badge {
		display: inline-block;
		font-size: 11px;
		font-weight: 600;
		padding: 4px 8px;
		border-radius: 9999px;
		flex-shrink: 0;
	}

	.badge-pass {
		background: rgba(76, 175, 124, 0.15);
		color: #4caf7c;
	}

	.badge-warn {
		background: rgba(232, 165, 76, 0.15);
		color: #e8a54c;
	}

	.badge-fail {
		background: rgba(224, 85, 85, 0.15);
		color: #e05555;
	}

	.check-name {
		font-size: 14px;
		color: var(--text);
	}

	.check-details {
		font-size: 11px;
		color: var(--text-dim);
		margin-left: auto;
	}
</style>
