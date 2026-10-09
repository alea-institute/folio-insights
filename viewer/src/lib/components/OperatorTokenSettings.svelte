<!--
	Settings popover holding the operator token (API authentication, drain plan U5).

	The API refuses state-changing requests without an operator token (401). The token is
	minted by `folio-insights api token-new` and held in this tab's memory only
	(`$lib/stores/llmKey`, `operatorToken`): never localStorage, sessionStorage, cookies or disk.
	`$lib/api/client` sends it as `Authorization: Bearer <token>` on same-origin API calls.
-->
<script lang="ts">
	import { forgetOperatorToken, operatorToken, setOperatorToken } from '$lib/stores/llmKey';

	const uid = Math.random().toString(36).slice(2, 8);
	const ids = { panel: `op-panel-${uid}`, input: `op-token-${uid}`, note: `op-note-${uid}` };

	let open = $state(false);
	let draft = $state('');
	let reveal = $state(false);
	let root: HTMLDivElement | undefined = $state();
	let input: HTMLInputElement | undefined = $state();
	let held = $derived($operatorToken.trim().length > 0);

	function toggle() {
		open = !open;
		if (open) {
			draft = '';
			reveal = false;
			queueMicrotask(() => input?.focus());
		}
	}

	function save(event: SubmitEvent) {
		event.preventDefault();
		if (!draft.trim()) return;
		setOperatorToken(draft);
		draft = '';
		reveal = false;
		open = false;
	}

	function forget() {
		forgetOperatorToken();
		draft = '';
	}

	function onWindowKeydown(event: KeyboardEvent) {
		if (open && event.key === 'Escape') open = false;
	}

	function onWindowPointerdown(event: PointerEvent) {
		if (open && root && !root.contains(event.target as Node)) open = false;
	}
</script>

<svelte:window onkeydown={onWindowKeydown} onpointerdown={onWindowPointerdown} />

<div class="op-settings" bind:this={root}>
	<button
		type="button"
		class="settings-btn"
		aria-label={held ? 'Settings (operator token held)' : 'Settings'}
		title="Settings"
		aria-haspopup="dialog"
		aria-expanded={open}
		aria-controls={ids.panel}
		onclick={toggle}
	>
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<circle cx="12" cy="12" r="3" />
			<path
				d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
			/>
		</svg>
		{#if held}<span class="badge" aria-hidden="true"></span>{/if}
	</button>

	{#if open}
		<div class="panel" id={ids.panel} role="dialog" aria-label="Settings">
			<form onsubmit={save}>
				<label for={ids.input}>Operator token</label>
				<div class="token-row">
					<input
						id={ids.input}
						bind:this={input}
						bind:value={draft}
						type={reveal ? 'text' : 'password'}
						placeholder={held ? 'Replace the held token' : 'fio_op_…'}
						autocomplete="off"
						autocapitalize="off"
						spellcheck="false"
						aria-describedby={ids.note}
					/>
					<button
						type="button"
						class="btn-toggle"
						aria-controls={ids.input}
						aria-pressed={reveal}
						onclick={() => (reveal = !reveal)}
					>
						{reveal ? 'Hide' : 'Show'}
					</button>
				</div>
				<p class="note" id={ids.note}>
					<span class="dot" class:held aria-hidden="true"></span>
					{#if held}
						A token is held in this tab's memory and sent with every change you make.
					{:else}
						Changes (uploads, reviews, jobs) need a token from
						<code>folio-insights api token-new</code>. Kept in this tab's memory only.
					{/if}
					Closing or reloading the tab clears it.
				</p>
				<div class="actions">
					{#if held}
						<button type="button" class="btn-link" onclick={forget}>Forget token</button>
					{/if}
					<button type="submit" class="btn-accent" disabled={!draft.trim()}>Use token</button>
				</div>
			</form>
		</div>
	{/if}
</div>

<style>
	.op-settings {
		position: relative;
		display: flex;
	}

	.settings-btn {
		position: relative;
		color: var(--text-dim);
		display: flex;
		align-items: center;
	}

	.settings-btn:hover,
	.settings-btn[aria-expanded='true'] {
		color: var(--text);
	}

	.badge {
		position: absolute;
		top: -2px;
		right: -3px;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--green);
		box-shadow: 0 0 0 2px var(--surface);
	}

	.panel {
		position: absolute;
		top: calc(100% + var(--sm));
		right: 0;
		z-index: 50;
		width: min(340px, calc(100vw - 2 * var(--md)));
		padding: var(--md);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
		animation: rise 140ms ease-out;
	}

	@keyframes rise {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.panel {
			animation: none;
		}
	}

	form {
		display: flex;
		flex-direction: column;
		gap: var(--sm);
	}

	label {
		font-size: 13px;
		font-weight: 500;
		color: var(--text);
	}

	.token-row {
		display: flex;
		gap: var(--xs);
	}

	input {
		flex: 1;
		min-width: 0;
		height: 32px;
		padding: var(--xs) var(--sm);
		background: var(--surface2);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 13px;
		letter-spacing: 0.3px;
		transition: border-color 150ms ease;
	}

	input:focus {
		border-color: var(--accent);
	}

	input::placeholder {
		color: var(--text-dim);
	}

	.btn-toggle {
		flex: none;
		min-width: 56px;
		height: 32px;
		padding: 0 var(--sm);
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--surface2);
		color: var(--text-dim);
		font-size: 12px;
	}

	.btn-toggle:hover,
	.btn-toggle[aria-pressed='true'] {
		color: var(--text);
	}

	.note {
		font-size: 12px;
		line-height: 1.45;
		color: var(--text-dim);
	}

	.note code {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 11px;
		color: var(--text);
	}

	.dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		margin-right: var(--xs);
		border-radius: 50%;
		background: var(--surface3);
		transform: translateY(-1px);
	}

	.dot.held {
		background: var(--green);
		box-shadow: 0 0 0 3px rgba(76, 175, 124, 0.18);
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: var(--sm);
	}

	.btn-link {
		margin-right: auto;
		font-size: 12px;
		color: var(--accent);
	}

	.btn-link:hover {
		text-decoration: underline;
	}

	.btn-accent {
		height: 30px;
		padding: 0 var(--md);
		border-radius: 4px;
		background: var(--accent);
		color: #fff;
		font-size: 13px;
		font-weight: 500;
	}

	.btn-accent:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
</style>
