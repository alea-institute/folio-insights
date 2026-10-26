<script lang="ts">
	import Layout from '../../../src/routes/+layout.svelte';
	let { children } = $props();
</script>

<Layout>{@render children()}</Layout>
