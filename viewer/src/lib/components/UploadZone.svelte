<script lang="ts">
	let { onfiles, disabled = false }: { onfiles: (files: FileList) => void; disabled?: boolean } =
		$props();

	let dragover = $state(false);
	let fileInput: HTMLInputElement;
	let folderInput: HTMLInputElement;
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
	class="upload-zone"
	class:dragover
	class:disabled
	role="button"
	tabindex="0"
	aria-label="Upload files. Drop files here or press Enter to open file picker."
	ondragover={(e) => {
		e.preventDefault();
		if (!disabled) dragover = true;
	}}
	ondragleave={() => (dragover = false)}
	ondrop={(e) => {
		e.preventDefault();
		dragover = false;
		if (!disabled && e.dataTransfer?.files.length) onfiles(e.dataTransfer.files);
	}}
	onclick={() => {
		if (!disabled) fileInput.click();
	}}
	onkeydown={(e) => {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			if (!disabled) fileInput.click();
		}
	}}
>
	<input
		bind:this={fileInput}
		type="file"
		multiple
		accept=".md,.txt,.docx,.pdf,.html,.rtf,.eml,.msg,.xml,.csv,.xlsx,.tsv,.wpd,.zip"
		style="display:none"
		onchange={(e) => {
			if (e.currentTarget.files?.length) onfiles(e.currentTarget.files);
		}}
	/>
	<input
		bind:this={folderInput}
		type="file"
		webkitdirectory
		style="display:none"
		onchange={(e) => {
			if (e.currentTarget.files?.length) onfiles(e.currentTarget.files);
		}}
	/>

	<svg
		class="upload-icon"
		width="24"
		height="24"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="1.5"
		stroke-linecap="round"
		stroke-linejoin="round"
	>
		<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
		<polyline points="17 8 12 3 7 8" />
		<line x1="12" y1="3" x2="12" y2="15" />
	</svg>

	<p class="upload-label">Drop files here or click to browse</p>
	<p class="upload-hint">
		Supports MD, TXT, DOCX, PDF, HTML, RTF, EML, MSG, XML, CSV, XLSX, TSV, WPD, and ZIP archives
	</p>

	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<span
		class="folder-link"
		role="button"
		tabindex="0"
		onclick={(e) => {
			e.stopPropagation();
			if (!disabled) folderInput.click();
		}}
		onkeydown={(e) => {
			e.stopPropagation();
			if ((e.key === 'Enter' || e.key === ' ') && !disabled) {
				e.preventDefault();
				folderInput.click();
			}
		}}
	>
		or upload a folder
	</span>
</div>

<style>
	.upload-zone {
		min-height: 120px;
		border: 2px dashed var(--border);
		border-radius: 8px;
		padding: var(--md);
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--xs);
		cursor: pointer;
		color: var(--text-dim);
		background: transparent;
		transition: all 200ms ease;
		user-select: none;
	}

	.upload-zone:hover {
		border-color: var(--accent-dim);
		color: var(--text);
	}

	.upload-zone.dragover {
		border-color: var(--accent);
		background: rgba(108, 140, 255, 0.05);
		color: var(--text);
	}

	.upload-zone.disabled {
		opacity: 0.5;
		pointer-events: none;
	}

	.upload-icon {
		margin-bottom: var(--xs);
	}

	.upload-label {
		font-size: 14px;
		font-weight: 500;
	}

	.upload-hint {
		font-size: 11px;
		max-width: 340px;
		line-height: 1.4;
	}

	.folder-link {
		font-size: 11px;
		color: var(--accent);
		cursor: pointer;
		margin-top: var(--xs);
	}

	.folder-link:hover {
		text-decoration: underline;
	}
</style>
