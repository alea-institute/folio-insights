<!-- viewer/src/routes/timeline/[id]/+page.svelte -->
<!-- D-09 supersession-timeline surface — critical-path render + {#await} streamed payloads. -->
<script lang="ts">
	import type { PageData } from './$types';
	let { data }: { data: PageData } = $props();
</script>

<svelte:head>
	<title>Timeline {data.timeline.label} — folio-insights</title>
</svelte:head>

<article>
	<h1>Timeline: {data.timeline.label}</h1>
	<dl>
		<dt>IRI</dt>
		<dd><code>{data.timeline.iri}</code></dd>
		<dt>Window</dt>
		<dd>{data.timeline.windowStart} → {data.timeline.windowEnd}</dd>
		<dt>Event count</dt>
		<dd>{data.timeline.eventCount}</dd>
	</dl>

	{#await data.events}
		<p><em>Loading events…</em></p>
	{:then ev}
		<section>
			<h2>Events</h2>
			<ul>
				{#each ev.events as e (e.id)}
					<li>{e.at}: {e.kind} — {e.summary}</li>
				{/each}
			</ul>
		</section>
	{:catch error}
		<p class="error">Failed to load events: {error.message}</p>
	{/await}

	{#await data.supersessionChain}
		<p><em>Loading supersession chain…</em></p>
	{:then chain}
		<section>
			<h2>Supersession chain</h2>
			<ol>
				{#each chain.supersession as s (s.iri)}
					<li><code>{s.iri}</code> (from {s.validFrom})</li>
				{/each}
			</ol>
		</section>
	{:catch error}
		<p class="error">Failed to load supersession chain: {error.message}</p>
	{/await}
</article>
