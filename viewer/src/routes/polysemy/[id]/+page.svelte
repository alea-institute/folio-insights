<!-- viewer/src/routes/polysemy/[id]/+page.svelte -->
<!-- D-09 polysemy-fork surface — critical-path render + {#await} streamed payloads. -->
<script lang="ts">
	import type { PageData } from './$types';
	let { data }: { data: PageData } = $props();
</script>

<svelte:head>
	<title>Polysemy {data.polysemy.label} — folio-insights</title>
</svelte:head>

<article>
	<h1>Polysemy: {data.polysemy.label}</h1>
	<dl>
		<dt>IRI</dt>
		<dd><code>{data.polysemy.iri}</code></dd>
		<dt>Primary sense</dt>
		<dd>{data.polysemy.primarySense}</dd>
		<dt>Fork count</dt>
		<dd>{data.polysemy.forkCount}</dd>
	</dl>

	{#await data.siblings}
		<p><em>Loading sibling senses…</em></p>
	{:then siblings}
		<section>
			<h2>Sibling senses</h2>
			<ul>
				{#each siblings.siblings as sib (sib.iri)}
					<li><code>{sib.iri}</code> — {sib.label}</li>
				{/each}
			</ul>
		</section>
	{:catch error}
		<p class="error">Failed to load siblings: {error.message}</p>
	{/await}

	{#await data.disambiguations}
		<p><em>Loading disambiguations…</em></p>
	{:then disamb}
		<section>
			<h2>Disambiguations</h2>
			<ul>
				{#each disamb.disambiguations as d (d.iri)}
					<li>{d.label}: {d.signal}</li>
				{/each}
			</ul>
		</section>
	{:catch error}
		<p class="error">Failed to load disambiguations: {error.message}</p>
	{/await}
</article>
