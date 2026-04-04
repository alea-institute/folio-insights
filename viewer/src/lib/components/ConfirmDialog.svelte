<script lang="ts">
	import { onMount } from 'svelte';

	let {
		open,
		title,
		message,
		confirmLabel,
		dismissLabel,
		variant = 'default',
		inputLabel = '',
		inputPlaceholder = '',
		inputValidation,
		loading = false,
		errorMessage = '',
		onconfirm,
		ondismiss,
	}: {
		open: boolean;
		title: string;
		message: string;
		confirmLabel: string;
		dismissLabel: string;
		variant?: 'default' | 'destructive' | 'input';
		inputLabel?: string;
		inputPlaceholder?: string;
		inputValidation?: (value: string) => string | null;
		loading?: boolean;
		errorMessage?: string;
		onconfirm: (value?: string) => void;
		ondismiss: () => void;
	} = $props();

	let inputValue = $state('');
	let validationError = $state<string | null>(null);
	let dialogEl: HTMLElement | undefined = $state();

	// Reset input when dialog opens
	$effect(() => {
		if (open) {
			inputValue = '';
			validationError = null;
		}
	});

	// Focus trap and initial focus
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

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;

		if (e.key === 'Escape') {
			e.preventDefault();
			if (!loading) ondismiss();
			return;
		}

		if (e.key === 'Enter') {
			e.preventDefault();
			if (!loading) handleConfirm();
			return;
		}

		// Focus trap
		if (e.key === 'Tab' && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				'button, input, [tabindex]:not([tabindex="-1"])'
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

	function handleConfirm() {
		if (loading) return;
		if (variant === 'input') {
			if (!inputValue.trim()) return;
			if (inputValidation) {
				const error = inputValidation(inputValue.trim());
				if (error) {
					validationError = error;
					return;
				}
			}
			onconfirm(inputValue.trim());
		} else {
			onconfirm();
		}
	}

	function handleInputChange() {
		if (validationError && inputValidation) {
			const error = inputValidation(inputValue.trim());
			if (!error) validationError = null;
		}
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="overlay" onclick={() => { if (!loading) ondismiss(); }} onkeydown={handleKeydown}>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="dialog"
			role="alertdialog"
			aria-modal="true"
			aria-labelledby="dialog-title"
			aria-describedby="dialog-message"
			onclick={(e) => e.stopPropagation()}
			onkeydown={handleKeydown}
			bind:this={dialogEl}
		>
			<h2 id="dialog-title" class="dialog-title">{title}</h2>
			<div id="dialog-message" class="dialog-message">
				{@html message}
			</div>

			{#if variant === 'input'}
				<div class="input-group">
					{#if inputLabel}
						<label for="dialog-input" class="input-label">{inputLabel}</label>
					{/if}
					<input
						id="dialog-input"
						type="text"
						class="dialog-input"
						class:error={validationError}
						placeholder={inputPlaceholder}
						bind:value={inputValue}
						oninput={handleInputChange}
						disabled={loading}
					/>
					{#if validationError}
						<p class="validation-error">{validationError}</p>
					{/if}
				</div>
			{/if}

			{#if errorMessage}
				<p class="error-message" role="alert">{errorMessage}</p>
			{/if}

			<div class="dialog-actions">
				<button class="btn btn-dismiss" onclick={ondismiss} disabled={loading}>
					{dismissLabel}
				</button>
				<button
					class="btn btn-confirm"
					class:btn-destructive={variant === 'destructive'}
					class:btn-accent={variant !== 'destructive'}
					disabled={(variant === 'input' && !inputValue.trim()) || loading}
					onclick={handleConfirm}
				>
					{#if loading}
						Creating...
					{:else}
						{confirmLabel}
					{/if}
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
		max-width: 400px;
		width: 90%;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
	}

	.dialog-title {
		font-size: 16px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: var(--sm);
	}

	.dialog-message {
		font-size: 14px;
		color: var(--text-dim);
		line-height: 1.5;
		margin-bottom: var(--md);
	}

	.input-group {
		margin-bottom: var(--md);
	}

	.input-label {
		display: block;
		font-size: 13px;
		color: var(--text-dim);
		margin-bottom: var(--xs);
	}

	.dialog-input {
		width: 100%;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: var(--xs) var(--sm);
		font-size: 14px;
		color: var(--text);
		transition: border-color 150ms ease;
	}

	.dialog-input:focus {
		border-color: var(--accent);
		outline: none;
	}

	.dialog-input.error {
		border-color: var(--red);
	}

	.dialog-input:disabled {
		opacity: 0.6;
	}

	.dialog-input::placeholder {
		color: var(--text-dim);
	}

	.validation-error {
		font-size: 11px;
		color: var(--red);
		margin-top: var(--xs);
	}

	.error-message {
		font-size: 13px;
		color: var(--red);
		margin-bottom: var(--md);
		padding: var(--xs) var(--sm);
		background: rgba(239, 68, 68, 0.08);
		border-radius: 4px;
		border: 1px solid rgba(239, 68, 68, 0.2);
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--sm);
	}

	.btn {
		padding: var(--xs) var(--md);
		font-size: 13px;
		border-radius: 4px;
		cursor: pointer;
		transition: opacity 150ms ease;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-dismiss {
		background: none;
		color: var(--text-dim);
	}

	.btn-dismiss:hover {
		color: var(--text);
	}

	.btn-destructive {
		background: var(--red);
		color: white;
	}

	.btn-destructive:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-accent {
		background: var(--accent);
		color: white;
	}

	.btn-accent:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
