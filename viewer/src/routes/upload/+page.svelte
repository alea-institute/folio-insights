<script lang="ts">
	import { selectedCorpus } from '$lib/stores/corpus';
</script>

<div class="upload-layout">
	<aside class="sidebar-placeholder">
		<p class="sidebar-note">Corpus sidebar will be added in Task 2</p>
	</aside>
	<div class="upload-main">
		{#if $selectedCorpus}
			<div class="upload-content">
				<p class="placeholder-text">Upload components will be added in Plan 04</p>
			</div>
		{:else}
			<div class="empty-state">
				<h2 class="empty-heading">No corpus selected</h2>
				<p class="empty-body">
					Create a new corpus or select an existing one from the sidebar.
				</p>
			</div>
		{/if}
	</div>
</div>

<style>
	.upload-layout {
		display: flex;
		height: 100%;
	}

	.sidebar-placeholder {
		width: 280px;
		flex-shrink: 0;
		background: var(--surface);
		border-right: 1px solid var(--border);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.sidebar-note {
		font-size: 13px;
		color: var(--text-dim);
		padding: var(--md);
		text-align: center;
	}

	.upload-main {
		flex: 1;
		padding: var(--md);
		overflow-y: auto;
	}

	.upload-content {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
	}

	.placeholder-text {
		font-size: 14px;
		color: var(--text-dim);
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: var(--sm);
	}

	.empty-heading {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.3px;
		color: var(--text);
	}

	.empty-body {
		font-size: 14px;
		color: var(--text-dim);
	}
</style>
