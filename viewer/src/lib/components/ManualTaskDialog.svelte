<script lang="ts">
	import type { TaskTreeNode } from '$lib/api/client';

	let {
		open,
		treeNodes,
		oncreate,
		ondismiss,
	}: {
		open: boolean;
		treeNodes: TaskTreeNode[];
		oncreate: (label: string, parentTaskId: string | null, taskType: string) => void;
		ondismiss: () => void;
	} = $props();

	let taskName = $state('');
	let parentTaskId = $state<string | null>(null);
	let taskType = $state<'categorical' | 'procedural'>('categorical');
	let validationError = $state<string | null>(null);
	let dialogEl: HTMLElement | undefined = $state();

	// Reset fields when dialog opens
	$effect(() => {
		if (open) {
			taskName = '';
			parentTaskId = null;
			taskType = 'categorical';
			validationError = null;
		}
	});

	// Focus trap and initial focus
	$effect(() => {
		if (open && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				'button, input, select, [tabindex]:not([tabindex="-1"])'
			);
			if (focusable.length > 0) {
				focusable[0].focus();
			}
		}
	});

	let taskParents = $derived(
		treeNodes.filter((n) => n.is_task)
	);

	function validate(): boolean {
		if (!taskName.trim()) {
			validationError = 'Task name is required.';
			return false;
		}
		if (taskName.trim().length < 2) {
			validationError = 'Task name must be at least 2 characters.';
			return false;
		}
		validationError = null;
		return true;
	}

	function handleSubmit() {
		if (!validate()) return;
		oncreate(taskName.trim(), parentTaskId, taskType);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;

		if (e.key === 'Escape') {
			e.preventDefault();
			ondismiss();
			return;
		}

		if (e.key === 'Enter' && (e.target as HTMLElement)?.tagName !== 'SELECT') {
			e.preventDefault();
			handleSubmit();
			return;
		}

		// Focus trap
		if (e.key === 'Tab' && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				'button, input, select, [tabindex]:not([tabindex="-1"])'
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
</script>

{#if open}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="overlay" onclick={ondismiss} onkeydown={handleKeydown}>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="dialog"
			role="alertdialog"
			aria-modal="true"
			aria-labelledby="mtd-title"
			aria-describedby="mtd-desc"
			onclick={(e) => e.stopPropagation()}
			onkeydown={handleKeydown}
			bind:this={dialogEl}
		>
			<h2 id="mtd-title" class="dialog-heading">New Task</h2>
			<p id="mtd-desc" class="dialog-desc">
				Create a new task manually. Name it, choose its parent in the FOLIO hierarchy, and assign knowledge units.
			</p>

			<div class="field-group">
				<label for="mtd-name" class="field-label">Task Name</label>
				<input
					id="mtd-name"
					type="text"
					class="field-input"
					class:field-error={validationError}
					placeholder="Task name"
					bind:value={taskName}
					oninput={() => { if (validationError) validationError = null; }}
				/>
				{#if validationError}
					<p class="validation-msg">{validationError}</p>
				{/if}
			</div>

			<div class="field-group">
				<label for="mtd-parent" class="field-label">FOLIO Parent</label>
				<select
					id="mtd-parent"
					class="field-select"
					bind:value={parentTaskId}
				>
					<option value={null}>No parent (top-level task)</option>
					{#each taskParents as node}
						<option value={node.id}>{node.label}</option>
					{/each}
				</select>
			</div>

			<div class="field-group">
				<span class="field-label">Task Type</span>
				<div class="type-toggle" role="radiogroup" aria-label="Task type">
					<button
						class="toggle-btn"
						class:active={taskType === 'categorical'}
						role="radio"
						aria-checked={taskType === 'categorical'}
						onclick={() => (taskType = 'categorical')}
					>
						Categorical
					</button>
					<button
						class="toggle-btn"
						class:active={taskType === 'procedural'}
						role="radio"
						aria-checked={taskType === 'procedural'}
						onclick={() => (taskType = 'procedural')}
					>
						Procedural
					</button>
				</div>
			</div>

			<div class="dialog-actions">
				<button class="btn btn-cancel" onclick={ondismiss}>
					Cancel
				</button>
				<button
					class="btn btn-create"
					disabled={!taskName.trim() || taskName.trim().length < 2}
					onclick={handleSubmit}
				>
					Create Task
				</button>
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
		max-width: 440px;
		width: 90%;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
	}

	.dialog-heading {
		font-size: 18px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: var(--xs);
	}

	.dialog-desc {
		font-size: 14px;
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
		color: var(--text-dim);
		margin-bottom: var(--xs);
	}

	.field-input {
		width: 100%;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: var(--sm);
		font-size: 14px;
		color: var(--text);
		transition: border-color 150ms ease;
	}

	.field-input:focus {
		border-color: var(--accent);
		outline: none;
	}

	.field-input.field-error {
		border-color: var(--red);
	}

	.field-input::placeholder {
		color: var(--text-dim);
	}

	.field-select {
		width: 100%;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: var(--sm);
		font-size: 14px;
		color: var(--text);
	}

	.field-select:focus {
		border-color: var(--accent);
		outline: none;
	}

	.validation-msg {
		font-size: 11px;
		color: var(--red);
		margin-top: var(--xs);
	}

	.type-toggle {
		display: flex;
		gap: 0;
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}

	.toggle-btn {
		flex: 1;
		padding: var(--xs) var(--sm);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		background: var(--surface2);
		color: var(--text-dim);
		transition: background 150ms ease, color 150ms ease;
		cursor: pointer;
	}

	.toggle-btn.active {
		background: var(--accent);
		color: #fff;
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

	.btn-cancel {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-dim);
	}

	.btn-cancel:hover {
		color: var(--text);
	}

	.btn-create {
		background: var(--accent);
		color: #fff;
		border: none;
	}

	.btn-create:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
