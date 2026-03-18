<script lang="ts">
	let { activePage }: { activePage: 'upload' | 'review' } = $props();
</script>

<nav class="nav-tabs" role="tablist" aria-label="Page navigation">
	<a
		href="/upload"
		role="tab"
		aria-selected={activePage === 'upload'}
		class="nav-tab"
		class:active={activePage === 'upload'}
		data-sveltekit-preload-data
	>
		Upload
	</a>
	<a
		href="/"
		role="tab"
		aria-selected={activePage === 'review'}
		class="nav-tab"
		class:active={activePage === 'review'}
		data-sveltekit-preload-data
	>
		Review
	</a>
</nav>

<style>
	.nav-tabs {
		display: flex;
		align-items: center;
		gap: var(--sm);
		height: 100%;
	}

	.nav-tab {
		display: flex;
		align-items: center;
		height: 100%;
		padding: 0 var(--xs);
		font-size: 13px;
		color: var(--text-dim);
		text-decoration: none;
		border-bottom: 2px solid transparent;
		transition: color 150ms ease, border-color 150ms ease;
	}

	.nav-tab:hover {
		color: var(--text);
	}

	.nav-tab.active {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}
</style>
