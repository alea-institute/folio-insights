<script lang="ts">
	let {
		files,
		onremove,
	}: {
		files: Array<{ filename: string; size_bytes: number; format: string; status?: string }>;
		onremove?: (filename: string) => void;
	} = $props();

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function extensionBadge(format: string): string {
		return format.replace(/^\./, '').toUpperCase().slice(0, 3);
	}
</script>

{#if files.length === 0}
	<div class="file-list-empty">
		<p class="empty-heading">No documents yet</p>
		<p class="empty-body">Upload files to this corpus using the drop zone above.</p>
	</div>
{:else}
	<div class="file-list" role="list" aria-label="Uploaded files">
		{#each files as file (file.filename)}
			<div class="file-item" role="listitem">
				<span class="format-badge">{extensionBadge(file.format)}</span>
				<span class="filename">{file.filename}</span>
				<span class="filesize">{formatSize(file.size_bytes)}</span>
				<span
					class="status-dot"
					class:pending={!file.status || file.status === 'pending'}
					class:processing={file.status === 'processing'}
					class:complete={file.status === 'complete'}
					class:error={file.status === 'error'}
					aria-label="Status: {file.status || 'pending'}"
				></span>
				{#if onremove}
					<button
						class="remove-btn"
						onclick={() => onremove?.(file.filename)}
						aria-label="Remove {file.filename}"
					>
						<svg
							width="12"
							height="12"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
						>
							<path d="M18 6L6 18M6 6l12 12" />
						</svg>
					</button>
				{/if}
			</div>
		{/each}
	</div>
{/if}

<style>
	.file-list-empty {
		padding: var(--lg);
		text-align: center;
	}

	.empty-heading {
		font-size: 14px;
		font-weight: 500;
		color: var(--text);
		margin-bottom: var(--xs);
	}

	.empty-body {
		font-size: 13px;
		color: var(--text-dim);
	}

	.file-list {
		display: flex;
		flex-direction: column;
		gap: var(--xs);
	}

	.file-item {
		display: flex;
		align-items: center;
		height: 36px;
		padding: var(--xs) var(--sm);
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		gap: var(--sm);
	}

	.format-badge {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--accent);
		background: rgba(108, 140, 255, 0.12);
		padding: 2px 4px;
		border-radius: 2px;
		flex-shrink: 0;
		min-width: 28px;
		text-align: center;
	}

	.filename {
		flex: 1;
		font-size: 14px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.filesize {
		font-size: 11px;
		color: var(--text-dim);
		flex-shrink: 0;
	}

	.status-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.status-dot.pending {
		background: var(--text-dim);
	}

	.status-dot.processing {
		background: var(--orange);
		animation: pulse 1000ms ease-in-out infinite;
	}

	.status-dot.complete {
		background: var(--green);
	}

	.status-dot.error {
		background: var(--red);
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.4;
		}
	}

	.remove-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		flex-shrink: 0;
		color: var(--text-dim);
		border-radius: 4px;
		opacity: 0;
		transition: opacity 150ms, color 150ms;
	}

	.file-item:hover .remove-btn {
		opacity: 1;
	}

	.remove-btn:hover {
		color: var(--red);
	}

	.remove-btn:focus-visible {
		opacity: 1;
	}
</style>
