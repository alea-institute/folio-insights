<script lang="ts">
	import {
		triggerExport,
		fetchExportValidation,
		getExportDownloadUrl,
		getExportBundleUrl,
	} from '$lib/api/client';
	import type { ExportValidationCheck } from '$lib/api/client';
	import ValidationSummary from '$lib/components/ValidationSummary.svelte';

	let {
		open,
		corpusId,
		hasApprovedTasks,
		ondismiss,
	}: {
		open: boolean;
		corpusId: string;
		hasApprovedTasks: boolean;
		ondismiss: () => void;
	} = $props();

	let dialogState = $state<'idle' | 'exporting' | 'complete' | 'error'>('idle');
	let errorMessage = $state('');
	let validationChecks = $state<ExportValidationCheck[]>([]);
	let dialogEl: HTMLElement | undefined = $state();

	// Format checkboxes
	let fmtOwl = $state(true);
	let fmtTtl = $state(true);
	let fmtJsonld = $state(false);
	let fmtHtml = $state(false);
	let fmtMd = $state(false);

	// Option checkboxes
	let optValidate = $state(true);
	let optChangelog = $state(true);

	let hasAnyFormat = $derived(fmtOwl || fmtTtl || fmtJsonld || fmtHtml || fmtMd);

	let selectedFormats = $derived.by(() => {
		const formats: string[] = [];
		if (fmtOwl) formats.push('owl');
		if (fmtTtl) formats.push('ttl');
		if (fmtJsonld) formats.push('jsonld');
		if (fmtHtml) formats.push('html');
		if (fmtMd) formats.push('md');
		return formats;
	});

	// Reset state when dialog opens
	$effect(() => {
		if (open) {
			dialogState = 'idle';
			errorMessage = '';
			validationChecks = [];
			fmtOwl = true;
			fmtTtl = true;
			fmtJsonld = false;
			fmtHtml = false;
			fmtMd = false;
			optValidate = true;
			optChangelog = true;
		}
	});

	// Focus first focusable element when dialog opens
	$effect(() => {
		if (open && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				'button, input, [tabindex]:not([tabindex="-1"])'
			);
			if (focusable.length > 0) {
				focusable[0].focus();
			}
		}
	});

	async function handleExport() {
		if (!hasAnyFormat || !hasApprovedTasks || !corpusId) return;
		dialogState = 'exporting';
		errorMessage = '';

		const result = await triggerExport(corpusId, selectedFormats);
		if ('error' in result) {
			dialogState = 'error';
			errorMessage = `Export failed: ${result.error}. Check that the corpus has approved tasks and try again.`;
			return;
		}

		// Fetch validation results
		if (optValidate) {
			const valResult = await fetchExportValidation(corpusId);
			if (!('error' in valResult)) {
				validationChecks = valResult.checks;
			}
		}

		dialogState = 'complete';
	}

	function handleDownload() {
		if (selectedFormats.length === 1) {
			window.location.href = getExportDownloadUrl(corpusId, selectedFormats[0]);
		} else {
			window.location.href = getExportBundleUrl(corpusId, selectedFormats);
		}
	}

	function handlePrimaryAction() {
		if (dialogState === 'idle') handleExport();
		else if (dialogState === 'complete') handleDownload();
		else if (dialogState === 'error') handleExport();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;

		if (e.key === 'Escape' && dialogState !== 'exporting') {
			e.preventDefault();
			ondismiss();
			return;
		}

		if (e.key === 'Enter') {
			e.preventDefault();
			handlePrimaryAction();
			return;
		}

		// Focus trap
		if (e.key === 'Tab' && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				'button, input, a, [tabindex]:not([tabindex="-1"])'
			);
			if (focusable.length === 0) return;

			const first = focusable[0];
			const last = focusable[focusable.length - 1];

			if (e.shiftKey) {
				if (document.activeElement === first) {
					e.preventDefault();
					last.focus();
				}
			} else {
				if (document.activeElement === last) {
					e.preventDefault();
					first.focus();
				}
			}
		}
	}

	function handleOverlayClick() {
		if (dialogState !== 'exporting') ondismiss();
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="overlay" onclick={handleOverlayClick} onkeydown={handleKeydown}>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="export-title"
			aria-describedby="export-desc"
			onclick={(e) => e.stopPropagation()}
			onkeydown={handleKeydown}
			bind:this={dialogEl}
		>
			<h2 id="export-title" class="dialog-heading">Export Ontology</h2>

			<button
				class="close-btn"
				onclick={ondismiss}
				aria-label="Close export dialog"
				disabled={dialogState === 'exporting'}
			>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M18 6L6 18M6 6l12 12" />
				</svg>
			</button>

			{#if !hasApprovedTasks}
				<div class="empty-state">
					<h3 class="empty-heading">No approved tasks</h3>
					<p class="empty-body">
						Approve tasks in the task tree before exporting. Use 'a' to approve the selected task or Shift+A to bulk approve high-confidence tasks.
					</p>
				</div>
			{:else}
				<p id="export-desc" class="dialog-desc">
					Export approved tasks and knowledge units as FOLIO-compatible ontology files.
				</p>

				<!-- FORMAT CHECKBOXES -->
				<div class="field-group">
					<span class="field-label">Output Formats</span>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={fmtOwl} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">OWL/XML (.owl)</span>
							<span class="checkbox-desc">Primary format for Protege and FOLIO toolchain</span>
						</span>
					</label>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={fmtTtl} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">Turtle (.ttl)</span>
							<span class="checkbox-desc">Human-readable RDF serialization</span>
						</span>
					</label>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={fmtJsonld} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">JSON-LD (.jsonld)</span>
							<span class="checkbox-desc">Per-task chunks for LLM RAG retrieval</span>
						</span>
					</label>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={fmtHtml} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">HTML browsable site</span>
							<span class="checkbox-desc">Static site with task navigation</span>
						</span>
					</label>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={fmtMd} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">Markdown outline</span>
							<span class="checkbox-desc">Comprehensive outline for reading</span>
						</span>
					</label>
				</div>

				<!-- OPTIONS -->
				<div class="field-group">
					<span class="field-label">Options</span>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={optValidate} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">Run SHACL validation</span>
						</span>
					</label>

					<label class="checkbox-row">
						<input type="checkbox" bind:checked={optChangelog} disabled={dialogState === 'exporting'} />
						<span class="checkbox-content">
							<span class="checkbox-label">Generate changelog (compares against previous export)</span>
						</span>
					</label>
				</div>

				<!-- Download links for completed export -->
				{#if dialogState === 'complete'}
					<div class="download-links">
						{#each selectedFormats as fmt}
							<a
								class="download-link"
								href={getExportDownloadUrl(corpusId, fmt)}
								download
							>
								{fmt.toUpperCase()}
							</a>
						{/each}
					</div>
				{/if}

				<!-- Validation Summary -->
				{#if dialogState === 'complete' && validationChecks.length > 0}
					<div class="validation-section">
						<ValidationSummary checks={validationChecks} />
					</div>
				{/if}

				<!-- Error message -->
				{#if dialogState === 'error'}
					<p class="error-message">{errorMessage}</p>
				{/if}
			{/if}

			<!-- BUTTONS -->
			<div class="dialog-actions">
				<button class="btn btn-close" onclick={ondismiss} disabled={dialogState === 'exporting'}>
					Close
				</button>
				{#if hasApprovedTasks}
					<button
						class="btn btn-primary"
						disabled={!hasAnyFormat || dialogState === 'exporting'}
						onclick={handlePrimaryAction}
					>
						{#if dialogState === 'idle'}
							Export Ontology
						{:else if dialogState === 'exporting'}
							Exporting...
						{:else if dialogState === 'complete'}
							Download Files
						{:else}
							Retry Export
						{/if}
					</button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 100;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.dialog {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: var(--lg);
		max-width: 480px;
		width: 90vw;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
		position: relative;
		max-height: 90vh;
		overflow-y: auto;
	}

	.dialog-heading {
		font-size: 18px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: var(--xs);
	}

	.close-btn {
		position: absolute;
		top: var(--lg);
		right: var(--lg);
		color: var(--text-dim);
		background: none;
		border: none;
		cursor: pointer;
		padding: 4px;
	}

	.close-btn:hover:not(:disabled) {
		color: var(--text);
	}

	.close-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.dialog-desc {
		font-size: 14px;
		font-weight: 400;
		color: var(--text-dim);
		line-height: 1.5;
		margin-bottom: var(--md);
	}

	.field-group {
		margin-bottom: var(--md);
	}

	.field-label {
		display: block;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-weight: 600;
		color: var(--text-dim);
		margin-bottom: var(--sm);
	}

	.checkbox-row {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 4px 0;
		cursor: pointer;
	}

	.checkbox-row input[type='checkbox'] {
		appearance: none;
		width: 16px;
		height: 16px;
		min-width: 16px;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		cursor: pointer;
		position: relative;
		margin-top: 2px;
		transition: background 150ms, border-color 150ms;
	}

	.checkbox-row input[type='checkbox']:checked {
		background: var(--accent);
		border-color: var(--accent);
	}

	.checkbox-row input[type='checkbox']:checked::after {
		content: '';
		position: absolute;
		left: 4px;
		top: 1px;
		width: 5px;
		height: 9px;
		border: solid white;
		border-width: 0 2px 2px 0;
		transform: rotate(45deg);
	}

	.checkbox-row input[type='checkbox']:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.checkbox-content {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.checkbox-label {
		font-size: 14px;
		color: var(--text);
	}

	.checkbox-desc {
		font-size: 11px;
		color: var(--text-dim);
	}

	.download-links {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sm);
		margin-bottom: var(--md);
	}

	.download-link {
		font-size: 11px;
		font-weight: 600;
		color: var(--accent);
		text-decoration: none;
		padding: 4px 8px;
		border: 1px solid var(--accent-dim);
		border-radius: 4px;
		transition: background 150ms;
	}

	.download-link:hover {
		background: var(--highlight);
	}

	.validation-section {
		margin-bottom: var(--md);
	}

	.error-message {
		font-size: 14px;
		color: var(--red);
		margin-bottom: var(--md);
		line-height: 1.5;
	}

	.empty-state {
		padding: var(--md) 0;
	}

	.empty-heading {
		font-size: 16px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: var(--sm);
	}

	.empty-body {
		font-size: 14px;
		color: var(--text-dim);
		line-height: 1.5;
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--sm);
		margin-top: var(--md);
	}

	.btn {
		padding: var(--xs) var(--md);
		font-size: 14px;
		font-weight: 600;
		border-radius: 4px;
		cursor: pointer;
		transition: opacity 150ms ease;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-close {
		background: transparent;
		border: none;
		color: var(--text-dim);
	}

	.btn-close:hover:not(:disabled) {
		color: var(--text);
	}

	.btn-primary {
		background: var(--accent);
		color: #fff;
		border: none;
	}

	.btn-primary:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
