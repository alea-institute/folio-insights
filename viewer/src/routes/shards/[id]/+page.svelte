<!-- viewer/src/routes/shards/[id]/+page.svelte -->
<!-- D-09 shard surface — critical-path render + {#await} streamed payloads. -->
<script lang="ts">
	import type { PageData } from './$types';
	let { data }: { data: PageData } = $props();
</script>

<svelte:head>
	<title>Shard {data.shard.label} — folio-insights</title>
</svelte:head>

<article>
	<h1>{data.shard.label}</h1>
	<dl>
		<dt>IRI</dt>
		<dd><code>{data.shard.iri}</code></dd>
		<dt>Confidence</dt>
		<dd>{data.shard.confidence}</dd>
		<dt>Corpus</dt>
		<dd>{data.shard.corpus}</dd>
		<dt>Valid from</dt>
		<dd>{data.shard.validFrom}</dd>
	</dl>

	{#await data.dependencies}
		<p><em>Loading dependencies…</em></p>
	{:then deps}
		<section>
			<h2>Dependencies</h2>
			<ul>
				{#each deps.dependsOnAxiom as axiom (axiom)}
					<li>Axiom: <code>{axiom}</code></li>
				{/each}
				{#each deps.dependsOnDefinition as def (def)}
					<li>Definition: <code>{def}</code></li>
				{/each}
			</ul>
		</section>
	{:catch error}
		<p class="error">Failed to load dependencies: {error.message}</p>
	{/await}

	{#await data.attestations}
		<p><em>Loading attestations…</em></p>
	{:then att}
		<section>
			<h2>Attestations</h2>
			<ul>
				{#each att.attestations as a (a.signer)}
					<li>{a.signer} (valid from {a.validFrom})</li>
				{/each}
			</ul>
		</section>
	{:catch error}
		<p class="error">Failed to load attestations: {error.message}</p>
	{/await}
</article>
