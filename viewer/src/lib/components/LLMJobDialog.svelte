<script lang="ts">
	/**
	 * Dialog that collects the per-session LLM settings for a job and runs the job action.
	 *
	 * The key is held in tab memory only ($lib/stores/llmKey); this component never writes it
	 * anywhere else. The dialog awaits `onsubmit` and stays open with an inline error on failure.
	 */
	import { tick, untrack } from 'svelte';
	import {
		PROVIDERS,
		providerById,
		llmSession,
		forgetKey,
		heldKeyFor,
		parseSpendCap,
		type LLMSession,
	} from '$lib/stores/llmKey';

	type Mode = 'submit' | 'resupply' | 'resume';

	let {
		open,
		mode = 'submit',
		title,
		intro = '',
		confirmLabel,
		onsubmit,
		onclose,
	}: {
		open: boolean;
		mode?: Mode;
		title: string;
		intro?: string;
		confirmLabel: string;
		/** Runs the job call with the chosen settings; resolve to an error message to stay open. */
		onsubmit: (settings: LLMSession) => Promise<string | null>;
		onclose: () => void;
	} = $props();

	const uid = Math.random().toString(36).slice(2, 8);
	const ids = {
		title: `llm-title-${uid}`,
		intro: `llm-intro-${uid}`,
		provider: `llm-provider-${uid}`,
		providerNote: `llm-provider-note-${uid}`,
		model: `llm-model-${uid}`,
		key: `llm-key-${uid}`,
		keyNote: `llm-key-note-${uid}`,
		cap: `llm-cap-${uid}`,
		capNote: `llm-cap-note-${uid}`,
	};

	let provider = $state('');
	let model = $state('');
	let apiKey = $state('');
	let capText = $state('');
	let showKey = $state(false);
	let capError = $state<string | null>(null);
	let keyError = $state<string | null>(null);
	let submitError = $state<string | null>(null);
	let busy = $state(false);
	let dialogEl: HTMLElement | undefined = $state();
	let returnFocus: HTMLElement | null = null;

	let selected = $derived(providerById(provider));
	let keyless = $derived(selected ? !selected.requiresKey : false);
	let keyHeld = $derived($llmSession.apiKey.trim().length > 0);
	let keyHeldFor = $derived(providerById($llmSession.keyProvider)?.label ?? 'this provider');
	let showProviderFields = $derived(mode === 'submit');
	let showCap = $derived(mode !== 'resupply');
	let keyRequired = $derived(mode === 'resupply' || (mode === 'submit' && !keyless));
	let showKeyField = $derived(!(mode === 'submit' && keyless));

	// Load the session values each time the dialog opens.
	$effect(() => {
		if (open) {
			// Read the session without subscribing: edits made while open must not reset the form.
			const s = untrack(() => $llmSession);
			provider = s.provider;
			model = s.model;
			// Resupply / resume act on a job pinned to the provider it was submitted with.
			apiKey = heldKeyFor(s, mode === 'submit' ? s.provider : s.keyProvider || s.provider);
			capText = mode === 'resume' ? '' : s.maxSpendUsd === null ? '' : String(s.maxSpendUsd);
			showKey = false;
			capError = null;
			keyError = null;
			submitError = null;
			busy = false;
			returnFocus = document.activeElement as HTMLElement | null;
			tick().then(() => {
				const first = dialogEl?.querySelector<HTMLElement>('select, input');
				first?.focus();
			});
		}
	});

	function focusables(): HTMLElement[] {
		if (!dialogEl) return [];
		return Array.from(
			dialogEl.querySelectorAll<HTMLElement>('button, input, select, [tabindex]:not([tabindex="-1"])')
		).filter((el) => !(el as HTMLButtonElement).disabled);
	}

	function close() {
		if (busy) return;
		onclose();
		returnFocus?.focus();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
			return;
		}
		if (e.key === 'Tab') {
			const items = focusables();
			if (items.length === 0) return;
			const first = items[0];
			const last = items[items.length - 1];
			if (e.shiftKey && document.activeElement === first) {
				e.preventDefault();
				last.focus();
			} else if (!e.shiftKey && document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}

	// Switching provider swaps in the key held for that provider (usually none).
	function handleProviderChange() {
		apiKey = heldKeyFor($llmSession, provider);
		showKey = false;
		keyError = null;
	}

	function handleForget() {
		forgetKey();
		apiKey = '';
		showKey = false;
	}

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (busy) return;
		submitError = null;

		const cap = showCap ? parseSpendCap(capText) : { value: null, error: null };
		capError = cap.error;
		const key = apiKey.trim();
		keyError = keyRequired && !key ? 'Enter your API key to continue.' : null;
		if (capError || keyError) return;

		// Commit to the in-memory session (never persisted). The key is bound to the provider
		// it was entered for; a keyless provider leaves any held key untouched and unsent.
		const s = $llmSession;
		const keyFor = mode === 'submit' ? provider : s.keyProvider || s.provider;
		const next: LLMSession = {
			provider: showProviderFields ? provider : s.provider,
			model: showProviderFields ? model.trim() : s.model,
			apiKey: showKeyField ? key : s.apiKey,
			keyProvider: showKeyField ? (key ? keyFor : '') : s.keyProvider,
			maxSpendUsd: mode === 'submit' ? cap.value : s.maxSpendUsd,
		};
		llmSession.set(next);

		busy = true;
		const error = await onsubmit({
			...next,
			apiKey: showKeyField ? key : '',
			maxSpendUsd: showCap ? cap.value : null,
		});
		busy = false;
		if (error) {
			submitError = error;
			return;
		}
		onclose();
		returnFocus?.focus();
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="overlay" onclick={close}>
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby={ids.title}
			aria-describedby={intro ? ids.intro : undefined}
			tabindex="-1"
			bind:this={dialogEl}
			onclick={(e) => e.stopPropagation()}
			onkeydown={handleKeydown}
		>
			<h2 id={ids.title} class="dialog-title">{title}</h2>
			{#if intro}
				<p id={ids.intro} class="dialog-intro">{intro}</p>
			{/if}

			<form onsubmit={handleSubmit} novalidate>
				{#if showProviderFields}
					<div class="field">
						<label for={ids.provider}>Provider</label>
						<select
							id={ids.provider}
							bind:value={provider}
							onchange={handleProviderChange}
							disabled={busy}
							aria-describedby={keyless ? ids.providerNote : undefined}
						>
							{#each PROVIDERS as p (p.id)}
								<option value={p.id}>{p.label}</option>
							{/each}
						</select>
						{#if keyless}
							<p id={ids.providerNote} class="note note-warn">
								Ollama runs on this server's own hardware and needs no key. The server's
								operator has to turn this on first; until they do, the job is refused.
							</p>
						{/if}
					</div>

					<div class="field">
						<label for={ids.model}>Model <span class="optional">(optional)</span></label>
						<input
							id={ids.model}
							type="text"
							bind:value={model}
							placeholder="Provider default"
							autocomplete="off"
							spellcheck="false"
							disabled={busy}
						/>
					</div>
				{/if}

				{#if showKeyField}
					<div class="field">
						<label for={ids.key}>
							API key
							{#if !keyRequired}<span class="optional">(optional)</span>{/if}
						</label>
						<div class="key-row">
							<input
								id={ids.key}
								type={showKey ? 'text' : 'password'}
								bind:value={apiKey}
								autocomplete="off"
								autocapitalize="off"
								spellcheck="false"
								aria-invalid={keyError ? 'true' : undefined}
								aria-describedby={ids.keyNote}
								aria-required={keyRequired ? 'true' : undefined}
								disabled={busy}
								oninput={() => (keyError = null)}
							/>
							<button
								type="button"
								class="btn-toggle"
								aria-controls={ids.key}
								aria-pressed={showKey}
								onclick={() => (showKey = !showKey)}
								disabled={busy}
							>
								{showKey ? 'Hide' : 'Show'}
							</button>
						</div>
						{#if keyError}
							<p class="field-error" role="alert">{keyError}</p>
						{/if}
						<div class="key-status">
							<span class="dot" class:held={keyHeld} aria-hidden="true"></span>
							<span id={ids.keyNote}>
								{#if keyHeld}
									A key for {keyHeldFor} is held in this tab's memory. Closing or reloading the
									tab clears it.
								{:else}
									Kept in this tab's memory only, never saved. Closing or reloading the tab
									clears it.
								{/if}
								{#if mode === 'resume'}
									{' '}Without a key the job waits until you supply one.
								{/if}
							</span>
							{#if keyHeld || apiKey}
								<button type="button" class="btn-link" onclick={handleForget} disabled={busy}>
									Forget key
								</button>
							{/if}
						</div>
					</div>
				{/if}

				{#if showCap}
					<div class="field">
						<label for={ids.cap}>
							{mode === 'resume' ? 'New spend cap (USD)' : 'Spend cap (USD)'}
							<span class="optional">(optional)</span>
						</label>
						<input
							id={ids.cap}
							type="text"
							inputmode="decimal"
							bind:value={capText}
							placeholder={mode === 'resume' ? 'Keep the current cap' : 'No cap'}
							autocomplete="off"
							aria-invalid={capError ? 'true' : undefined}
							aria-describedby={ids.capNote}
							disabled={busy}
							oninput={() => (capError = null)}
						/>
						{#if capError}
							<p class="field-error" role="alert">{capError}</p>
						{/if}
						<p id={ids.capNote} class="note">
							The job pauses when its LLM spend reaches this amount.
						</p>
					</div>
				{/if}

				{#if submitError}
					<p class="submit-error" role="alert">{submitError}</p>
				{/if}

				<div class="actions">
					<button type="button" class="btn btn-dismiss" onclick={close} disabled={busy}>
						Cancel
					</button>
					<button type="submit" class="btn btn-accent" disabled={busy} aria-busy={busy}>
						{busy ? 'Working...' : confirmLabel}
					</button>
				</div>
			</form>
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
		padding: var(--md);
	}

	.dialog {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: var(--lg);
		max-width: 440px;
		width: 100%;
		max-height: 100%;
		overflow-y: auto;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
	}

	.dialog:focus {
		outline: none;
	}

	.dialog-title {
		font-size: 16px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: var(--xs);
	}

	.dialog-intro {
		font-size: 13px;
		color: var(--text-dim);
		line-height: 1.5;
		margin-bottom: var(--md);
	}

	form {
		display: flex;
		flex-direction: column;
		gap: var(--md);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--xs);
	}

	label {
		font-size: 13px;
		color: var(--text);
		font-weight: 500;
	}

	.optional {
		color: var(--text-dim);
		font-weight: 400;
	}

	input,
	select {
		width: 100%;
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: var(--xs) var(--sm);
		height: 32px;
		font-size: 14px;
		color: var(--text);
		transition: border-color 150ms ease;
	}

	input:focus,
	select:focus {
		border-color: var(--accent);
	}

	input[aria-invalid='true'] {
		border-color: var(--red);
	}

	input:disabled,
	select:disabled {
		opacity: 0.6;
	}

	input::placeholder {
		color: var(--text-dim);
	}

	.key-row {
		display: flex;
		gap: var(--xs);
	}

	.key-row input {
		flex: 1;
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		letter-spacing: 0.3px;
	}

	.btn-toggle {
		flex: none;
		min-width: 56px;
		height: 32px;
		padding: 0 var(--sm);
		border-radius: 4px;
		border: 1px solid var(--border);
		background: var(--surface2);
		color: var(--text-dim);
		font-size: 12px;
	}

	.btn-toggle:hover:not(:disabled),
	.btn-toggle[aria-pressed='true'] {
		color: var(--text);
	}

	.key-status {
		display: flex;
		align-items: baseline;
		gap: var(--sm);
		font-size: 12px;
		color: var(--text-dim);
		line-height: 1.45;
	}

	.dot {
		flex: none;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--surface3);
		transform: translateY(-1px);
	}

	.dot.held {
		background: var(--green);
		box-shadow: 0 0 0 3px rgba(76, 175, 124, 0.18);
	}

	.btn-link {
		flex: none;
		margin-left: auto;
		font-size: 12px;
		color: var(--accent);
		padding: 0 var(--xs);
	}

	.btn-link:hover:not(:disabled) {
		text-decoration: underline;
	}

	.note {
		font-size: 12px;
		color: var(--text-dim);
		line-height: 1.45;
	}

	.note-warn {
		color: var(--orange);
	}

	.field-error {
		font-size: 12px;
		color: var(--red);
	}

	.submit-error {
		font-size: 13px;
		color: var(--red);
		padding: var(--xs) var(--sm);
		background: rgba(224, 85, 85, 0.08);
		border: 1px solid rgba(224, 85, 85, 0.25);
		border-radius: 4px;
		overflow-wrap: anywhere;
	}

	.actions {
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

	.btn-dismiss:hover:not(:disabled) {
		color: var(--text);
	}

	.btn-accent {
		background: var(--accent);
		color: #fff;
		font-weight: 600;
	}

	.btn-accent:hover:not(:disabled) {
		opacity: 0.9;
	}

	@media (prefers-reduced-motion: reduce) {
		input,
		select,
		.btn {
			transition: none;
		}
	}
</style>
