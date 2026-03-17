<script lang="ts">
	let { score }: { score: number } = $props();

	let display = $derived(Math.round(score * 100));
	let band = $derived(score >= 0.8 ? 'high' : score >= 0.5 ? 'medium' : 'low');
	let showStar = $derived(display >= 80);
</script>

<span class="badge badge-{band}" title="Confidence: {display}%">
	{display}{#if showStar}<span class="star" aria-hidden="true">*</span>{/if}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		padding: 1px 8px;
		border-radius: 9999px;
		font-size: 11px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		line-height: 1.3;
	}

	.badge-high {
		background: rgba(76, 175, 124, 0.15);
		color: #4caf7c;
	}

	.badge-medium {
		background: rgba(232, 165, 76, 0.15);
		color: #e8a54c;
	}

	.badge-low {
		background: rgba(224, 85, 85, 0.15);
		color: #e05555;
	}

	.star {
		margin-left: 2px;
	}
</style>
