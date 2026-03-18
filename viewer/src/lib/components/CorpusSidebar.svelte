<script lang="ts">
	import {
		corpora,
		selectedCorpus,
		createCorpus,
		deleteCorpus,
		selectCorpus,
	} from '$lib/stores/corpus';
	import type { CorpusInfo } from '$lib/api/client';
	import ConfirmDialog from './ConfirmDialog.svelte';

	let showCreateDialog = $state(false);
	let showDeleteDialog = $state(false);
	let deleteTarget = $state<CorpusInfo | null>(null);

	function handleCreate(value?: string) {
		if (value) {
			createCorpus(value);
		}
		showCreateDialog = false;
	}

	function handleDeleteClick(e: MouseEvent, corpus: CorpusInfo) {
		e.stopPropagation();
		deleteTarget = corpus;
		showDeleteDialog = true;
	}

	function handleDeleteConfirm() {
		if (deleteTarget) {
			deleteCorpus(deleteTarget.id);
		}
		showDeleteDialog = false;
		deleteTarget = null;
	}

	function handleDeleteDismiss() {
		showDeleteDialog = false;
		deleteTarget = null;
	}

	function validateCorpusName(name: string): string | null {
		const exists = $corpora.some((c) => c.name.toLowerCase() === name.toLowerCase());
		if (exists) return 'A corpus with this name already exists.';
		return null;
	}

	function formatStatus(corpus: CorpusInfo): string {
		if (corpus.processing_status === 'processing') return 'Processing...';
		if (corpus.last_processed) {
			const date = new Date(corpus.last_processed);
			return `Processed ${date.toLocaleDateString()}`;
		}
		return 'Not processed';
	}

	function formatFileCount(count: number): string {
		if (count === 0) return 'No files';
		if (count === 1) return '1 file';
		return `${count} files`;
	}
</script>

<div class="corpus-sidebar">
	<div class="sidebar-header">
		<h3 class="sidebar-heading">Corpora</h3>
		<button class="new-corpus-btn" onclick={() => (showCreateDialog = true)}>
			+ New Corpus
		</button>
	</div>

	<div class="corpus-list" role="listbox" aria-label="Corpus list">
		{#each $corpora as corpus}
			{@const isSelected = $selectedCorpus?.id === corpus.id}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<div
				class="corpus-item"
				class:selected={isSelected}
				role="option"
				aria-selected={isSelected}
				onclick={() => selectCorpus(corpus)}
				onkeydown={(e) => {
					if (e.key === 'Enter' || e.key === ' ') {
						e.preventDefault();
						selectCorpus(corpus);
					}
				}}
				tabindex="0"
			>
				<div class="corpus-info">
					<span class="corpus-name">{corpus.name}</span>
					<span class="corpus-meta">
						{formatFileCount(corpus.file_count)} &middot; {formatStatus(corpus)}
					</span>
				</div>
				<button
					class="delete-btn"
					onclick={(e) => handleDeleteClick(e, corpus)}
					aria-label="Delete {corpus.name}"
				>
					<svg
						width="14"
						height="14"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
					>
						<path d="M18 6L6 18M6 6l12 12" />
					</svg>
				</button>
			</div>
		{/each}

		{#if $corpora.length === 0}
			<div class="empty-list">
				<p>No corpora yet</p>
			</div>
		{/if}
	</div>
</div>

<!-- Create corpus dialog -->
<ConfirmDialog
	open={showCreateDialog}
	title="Create Corpus"
	message="Enter a name for the new corpus."
	confirmLabel="Create Corpus"
	dismissLabel="Discard"
	variant="input"
	inputLabel="Corpus Name"
	inputPlaceholder="Enter a name for the new corpus"
	inputValidation={validateCorpusName}
	onconfirm={handleCreate}
	ondismiss={() => (showCreateDialog = false)}
/>

<!-- Delete corpus dialog -->
<ConfirmDialog
	open={showDeleteDialog}
	title="Delete Corpus"
	message={deleteTarget
		? `This will permanently delete <strong>${deleteTarget.name}</strong> and all its uploaded files and extraction results. This cannot be undone.`
		: ''}
	confirmLabel="Delete Corpus"
	dismissLabel="Keep Corpus"
	variant="destructive"
	onconfirm={handleDeleteConfirm}
	ondismiss={handleDeleteDismiss}
/>

<style>
	.corpus-sidebar {
		width: 280px;
		flex-shrink: 0;
		background: var(--surface);
		border-right: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.sidebar-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--sm) var(--sm);
		border-bottom: 1px solid var(--border);
	}

	.sidebar-heading {
		font-size: 13px;
		font-weight: 400;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-dim);
	}

	.new-corpus-btn {
		font-size: 13px;
		color: var(--accent);
		cursor: pointer;
		padding: var(--xs) var(--sm);
		border-radius: 4px;
		transition: opacity 150ms ease;
	}

	.new-corpus-btn:hover {
		opacity: 0.8;
	}

	.corpus-list {
		flex: 1;
		overflow-y: auto;
	}

	.corpus-item {
		display: flex;
		align-items: center;
		height: 48px;
		padding: 0 var(--sm);
		cursor: pointer;
		transition: background 100ms;
		position: relative;
	}

	.corpus-item:hover {
		background: var(--surface2);
	}

	.corpus-item.selected {
		background: var(--highlight);
		border-left: 2px solid var(--accent);
	}

	.corpus-info {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: center;
		min-width: 0;
	}

	.corpus-name {
		font-size: 13px;
		font-weight: 400;
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.corpus-meta {
		font-size: 11px;
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.delete-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		flex-shrink: 0;
		color: var(--text-dim);
		border-radius: 4px;
		opacity: 0;
		transition: opacity 150ms, color 150ms;
	}

	.corpus-item:hover .delete-btn {
		opacity: 1;
	}

	.delete-btn:hover {
		color: var(--red);
	}

	.delete-btn:focus-visible {
		opacity: 1;
	}

	.empty-list {
		padding: var(--lg);
		text-align: center;
	}

	.empty-list p {
		font-size: 13px;
		color: var(--text-dim);
	}
</style>
