<script lang="ts">
	import { submitReview } from '$lib/stores/review';
	import { bulkApprove } from '$lib/api/client';
	import { units, selectedUnit, refreshStats, loadUnits } from '$lib/stores/review';
	import { selectedConcept, confidenceFilter } from '$lib/stores/tree';
	import { editorOpen } from '$lib/stores/review';

	let { unitId, corpus = 'default' }: { unitId: string; corpus?: string } = $props();

	async function approve() {
		await submitReview(unitId, 'approved', corpus);
	}

	async function reject() {
		await submitReview(unitId, 'rejected', corpus);
	}

	function edit() {
		$editorOpen = true;
	}

	function skip() {
		// Move to next unit without making a decision
		const list = $units;
		const idx = list.findIndex((u) => u.id === unitId);
		if (idx >= 0 && idx < list.length - 1) {
			$selectedUnit = list[idx + 1];
		}
	}

	async function approveAllHigh() {
		const result = await bulkApprove(corpus, undefined, 0.8);
		if (!('error' in result)) {
			await refreshStats(corpus);
			const concept = $selectedConcept;
			if (concept) {
				const conf = $confidenceFilter === 'all' ? undefined : $confidenceFilter;
				await loadUnits(corpus, concept.iri, conf);
			}
		}
	}
</script>

<div class="review-controls" role="toolbar" aria-label="Review actions">
	<button class="btn btn-approve" onclick={approve} title="Approve (A)">
		Approve
	</button>
	<button class="btn btn-reject" onclick={reject} title="Reject (R)">
		Reject
	</button>
	<button class="btn btn-edit" onclick={edit} title="Edit (E)">
		Edit
	</button>
	<button class="btn btn-skip" onclick={skip} title="Skip (S)">
		Skip
	</button>
	<button class="btn btn-bulk" onclick={approveAllHigh} title="Approve All High (Shift+A)">
		Approve All
	</button>
</div>

<style>
	.review-controls {
		display: flex;
		gap: var(--xs);
		align-items: center;
		flex-wrap: wrap;
	}

	.btn {
		height: 36px;
		padding: 0 var(--sm);
		border-radius: 4px;
		font-size: 13px;
		font-weight: 600;
		transition: opacity 150ms, transform 150ms;
	}

	.btn:hover {
		opacity: 0.85;
	}

	.btn:active {
		transform: scale(0.97);
	}

	.btn-approve {
		background: var(--green);
		color: #fff;
	}

	.btn-reject {
		background: transparent;
		border: 1px solid var(--red);
		color: var(--red);
	}

	.btn-edit {
		background: transparent;
		border: 1px solid var(--accent);
		color: var(--accent);
	}

	.btn-skip {
		color: var(--text-dim);
		font-weight: 400;
	}

	.btn-bulk {
		background: var(--green);
		color: #fff;
		margin-left: auto;
	}
</style>
