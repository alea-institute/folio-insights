<script lang="ts">
	import AnnotatedText from '$lib/components/AnnotatedText.svelte';
	import Chip from '$lib/components/Chip.svelte';
	import ReviewCard from '$lib/components/ReviewCard.svelte';

	const text = 'A party must give notice. 😀 Notice may be delayed. <img src=x onerror="window.fixtureExecuted=true">';
	let selected = $state(false);
	let confirmed = $state(false);
</script>

<div class="workbench-page">
	<header class="workbench-heading">
		<h2>Review the source</h2>
		<p>Synthetic notice rule. Component fixture; no legal authority.</p>
	</header>
	<div class="workbench-columns">
		<section class="source-panel" aria-label="Source text">
			<h3>Notice and delay</h3>
			<AnnotatedText {text} spans={[
				{ id: 'duty', start: 0, end: 24, label: 'Notice duty' },
				{ id: 'notice', start: 18, end: 35, label: 'Notice overlap' },
				{ id: 'permission', start: 28, end: 51, label: 'Delay permission' },
				{ id: 'invalid', start: -1, end: 999 },
			]} />
		</section>
		<ReviewCard title="A party must give notice" verdict="uncertain" reason="Review whether the exception applies.">
			<Chip label="Obligation" branch="Deontic Specification" verdict="correct" onclick={() => selected = !selected} pressed={selected} />
			<Chip label="Notice" branch="Legal Process" tone="process" confidence="medium" verdict="uncertain" />
			<Chip label="Party" branch="Actor" tone="actor" confidence="low" verdict="wrong" />
			{#snippet actions()}
				<button type="button" onclick={() => confirmed = true}>Confirm proposition</button>
			{/snippet}
		</ReviewCard>
	</div>
	<p role="status">{confirmed ? 'Proposition confirmed in fixture' : selected ? 'Obligation selected' : ''}</p>
</div>
