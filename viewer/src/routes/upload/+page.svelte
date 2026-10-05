<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { selectedCorpus } from '$lib/stores/corpus';
	import {
		processingStatus,
		currentStage,
		progressPct,
		activityLog,
		totalUnits,
		processingError,
		processingPause,
		sseState,
		startProcessingStream,
		closeStream,
		resetProcessing,
	} from '$lib/stores/processing';
	import {
		discoveryStatus,
		discoveryStage,
		discoveryProgress,
		discoveryLog,
		discoveryError,
		discoveryPause,
		startDiscoveryStream,
		closeDiscoveryStream,
		resetDiscovery,
	} from '$lib/stores/discovery';
	import { uploadFiles, fetchCorpusFiles } from '$lib/api/client';
	import type { CorpusFile } from '$lib/api/client';
	import {
		submitJob,
		cancelJob,
		resupplyJobKey,
		resumeJob,
		isJobError,
		type JobKind,
	} from '$lib/api/jobs';
	import { isFinished, mapJobStatus } from '$lib/stores/jobStatus';
	import {
		llmSession,
		controlTokens,
		setControlToken,
		getControlToken,
		clearControlToken,
		type LLMSession,
	} from '$lib/stores/llmKey';

	import CorpusSidebar from '$lib/components/CorpusSidebar.svelte';
	import UploadZone from '$lib/components/UploadZone.svelte';
	import FileListView from '$lib/components/FileList.svelte';
	import ProcessButton from '$lib/components/ProcessButton.svelte';
	import ProgressDisplay from '$lib/components/ProgressDisplay.svelte';
	import ActivityLog from '$lib/components/ActivityLog.svelte';
	import DiscoverButton from '$lib/components/DiscoverButton.svelte';
	import DiscoveryProgress from '$lib/components/DiscoveryProgress.svelte';
	import LLMJobDialog from '$lib/components/LLMJobDialog.svelte';
	import JobPausedPanel from '$lib/components/JobPausedPanel.svelte';

	let files = $state<Array<{ filename: string; size_bytes: number; format: string; status: string }>>([]);
	let uploading = $state(false);
	let activityExpanded = $state(false);
	let navTimer: ReturnType<typeof setTimeout> | null = null;
	let discoveryNavTimer: ReturnType<typeof setTimeout> | null = null;

	// Load files when corpus changes
	$effect(() => {
		const corpus = $selectedCorpus;
		if (corpus) {
			resetProcessing();
			resetDiscovery();
			loadFiles(corpus.id);
		} else {
			files = [];
			resetProcessing();
			resetDiscovery();
		}
	});

	// Auto-navigate on completion
	$effect(() => {
		if ($processingStatus === 'complete' && $selectedCorpus) {
			const corpusId = $selectedCorpus.id;
			navTimer = setTimeout(() => {
				goto(`/?corpus=${corpusId}`);
			}, 1500);
		}
	});

	// Auto-navigate to tasks on discovery completion
	$effect(() => {
		if ($discoveryStatus === 'complete') {
			discoveryNavTimer = setTimeout(() => {
				goto('/tasks');
			}, 1500);
			return () => {
				if (discoveryNavTimer) clearTimeout(discoveryNavTimer);
			};
		}
	});

	// Auto-expand activity log on error
	$effect(() => {
		if ($processingStatus === 'error') {
			activityExpanded = true;
		}
	});

	// Status announcement text for screen readers
	let statusAnnouncement = $derived(
		$discoveryStatus === 'processing' && $discoveryStage
			? `Discovery stage: ${$discoveryStage}`
			: $discoveryStatus === 'complete'
				? 'Task discovery complete.'
				: $discoveryStatus === 'paused'
					? 'Task discovery paused. Action needed.'
				: $processingStatus === 'paused'
					? 'Processing paused. Action needed.'
				: $processingStatus === 'processing' && $currentStage
					? `Processing stage: ${$currentStage}`
					: $processingStatus === 'complete'
						? `Processing complete. ${$totalUnits} knowledge units extracted.`
						: $processingStatus === 'error'
							? `Processing failed. ${$processingError || 'Check the activity log for details.'}`
							: ''
	);

	// Derive discovery button status
	let discoverStatus = $derived<'ready' | 'disabled' | 'processing' | 'complete'>(
		$discoveryStatus === 'complete'
			? 'complete'
			: $discoveryStatus === 'processing'
				? 'processing'
				: $processingStatus === 'complete'
					? 'ready'
					: 'disabled'
	);

	async function loadFiles(corpusId: string) {
		const result = await fetchCorpusFiles(corpusId);
		if (!('error' in result)) {
			files = result.map((f: CorpusFile) => ({
				filename: f.filename,
				size_bytes: f.size_bytes,
				format: f.format,
				status: 'pending',
			}));
		}
	}

	async function handleFiles(fileList: FileList) {
		if (!$selectedCorpus) return;
		uploading = true;
		const result = await uploadFiles($selectedCorpus.id, fileList);
		if (!('error' in result)) {
			await loadFiles($selectedCorpus.id);
		}
		uploading = false;
	}

	function handleProcess() {
		if (!$selectedCorpus) return;
		openDialog('process', 'submit');
	}

	function handleDiscover() {
		if (!$selectedCorpus) return;
		openDialog('discover', 'submit');
	}

	// -----------------------------------------------------------------------
	// LLM jobs: the key lives in tab memory ($lib/stores/llmKey) and is sent
	// only as a header on submit / resume / re-supply ($lib/api/jobs).
	// -----------------------------------------------------------------------

	type DialogMode = 'submit' | 'resupply' | 'resume';
	let dialog = $state<{ open: boolean; kind: JobKind; mode: DialogMode }>({
		open: false,
		kind: 'process',
		mode: 'submit',
	});
	let controlBusy = $state<Record<JobKind, boolean>>({ process: false, discover: false });
	let controlError = $state<Record<JobKind, string | null>>({ process: null, discover: null });
	let cancelRequested = $state<Record<JobKind, boolean>>({ process: false, discover: false });

	let keyHeld = $derived($llmSession.apiKey.trim().length > 0);
	let processToken = $derived($selectedCorpus ? $controlTokens[`process:${$selectedCorpus.id}`] : undefined);
	let discoverToken = $derived($selectedCorpus ? $controlTokens[`discover:${$selectedCorpus.id}`] : undefined);

	const JOB_LABEL: Record<JobKind, string> = { process: 'Processing', discover: 'Task discovery' };

	let dialogTitle = $derived(
		dialog.mode === 'resupply'
			? 'Supply your API key'
			: dialog.mode === 'resume'
				? 'Resume after the spend cap'
				: dialog.kind === 'discover'
					? 'Discover tasks'
					: 'Process corpus'
	);
	let dialogIntro = $derived(
		dialog.mode === 'resupply'
			? `${JOB_LABEL[dialog.kind]} is waiting for a key. It is sent once, in a request header, and held only in the server's memory for this job.`
			: dialog.mode === 'resume'
				? 'Set a higher cap if you want the job to spend more, and supply your key so it can continue.'
				: 'This job calls an LLM with your own API key. The key is sent only in a request header and is never saved.'
	);
	let dialogConfirm = $derived(
		dialog.mode === 'resupply'
			? 'Continue job'
			: dialog.mode === 'resume'
				? 'Resume job'
				: dialog.kind === 'discover'
					? 'Start discovery'
					: 'Start processing'
	);

	function startStream(kind: JobKind, corpusId: string) {
		if (kind === 'process') startProcessingStream(corpusId);
		else startDiscoveryStream(corpusId);
	}

	function openDialog(kind: JobKind, mode: DialogMode) {
		controlError[kind] = null;
		dialog = { open: true, kind, mode };
	}

	async function runDialog(settings: LLMSession): Promise<string | null> {
		const corpus = $selectedCorpus;
		if (!corpus) return 'Select a corpus first.';
		const { kind, mode } = dialog;

		if (mode === 'submit') {
			const res = await submitJob(
				kind,
				corpus.id,
				{
					provider: settings.provider,
					model: settings.model,
					apiKey: settings.apiKey,
					maxSpendUsd: settings.maxSpendUsd,
				},
				kind === 'process'
			);
			if (isJobError(res)) return res.error;
			if (res.control_token) setControlToken(kind, corpus.id, res.control_token);
			cancelRequested[kind] = false;
			startStream(kind, corpus.id);
			return null;
		}

		const token = getControlToken(kind, corpus.id);
		if (!token) return "This tab no longer holds the job's control token.";
		const res =
			mode === 'resupply'
				? await resupplyJobKey(kind, corpus.id, token, settings.apiKey)
				: await resumeJob(kind, corpus.id, token, {
						apiKey: settings.apiKey,
						maxSpendUsd: settings.maxSpendUsd,
					});
		if (isJobError(res)) return res.error;
		startStream(kind, corpus.id);
		return null;
	}

	function continuePaused(kind: JobKind) {
		const reason = kind === 'process' ? $processingPause : $discoveryPause;
		openDialog(kind, reason === 'budget_exhausted' ? 'resume' : 'resupply');
	}

	async function handleCancel(kind: JobKind) {
		const corpus = $selectedCorpus;
		if (!corpus) return;
		const token = getControlToken(kind, corpus.id);
		if (!token) return;
		controlBusy[kind] = true;
		controlError[kind] = null;
		const res = await cancelJob(kind, corpus.id, token);
		controlBusy[kind] = false;
		if (isJobError(res)) {
			controlError[kind] = res.error;
			return;
		}
		if (isFinished(res.status)) {
			// Cancelled while waiting: the stream is already closed, so settle the UI here.
			clearControlToken(kind, corpus.id);
			if (kind === 'process') {
				closeStream();
				processingPause.set(null);
				processingStatus.set(mapJobStatus(res.status));
			} else {
				closeDiscoveryStream();
				discoveryPause.set(null);
				discoveryStatus.set(mapJobStatus(res.status));
			}
		} else {
			// Running: the job stops at the next stage boundary and the stream reports it.
			cancelRequested[kind] = true;
		}
	}

	function handleRemoveFile(filename: string) {
		files = files.filter((f) => f.filename !== filename);
	}

	onDestroy(() => {
		closeStream();
		closeDiscoveryStream();
		if (navTimer) clearTimeout(navTimer);
		if (discoveryNavTimer) clearTimeout(discoveryNavTimer);
	});
</script>

<div class="upload-layout">
	<CorpusSidebar />
	<div class="upload-main">
		{#if !$selectedCorpus}
			<div class="empty-state">
				<h2 class="empty-heading">No corpus selected</h2>
				<p class="empty-body">
					Create a new corpus or select an existing one from the sidebar.
				</p>
			</div>
		{:else if $processingStatus === 'complete'}
			<!-- Complete state: green progress, success message, discovery trigger -->
			<div class="upload-content">
				<ProgressDisplay
					progress={100}
					currentStage=""
					status="complete"
				/>
				<p class="success-text">
					Processing complete &mdash; {files.length} files processed, {$totalUnits} knowledge units extracted.
				</p>
				{#if $discoveryStatus === 'paused' && $discoveryPause}
					<DiscoveryProgress
						currentStage={$discoveryStage}
						progress={$discoveryProgress}
						status="paused"
					/>
					<JobPausedPanel
						jobLabel="Task discovery"
						reason={$discoveryPause}
						detail={$discoveryError}
						canControl={!!discoverToken}
						{keyHeld}
						busy={controlBusy.discover}
						error={controlError.discover}
						oncontinue={() => continuePaused('discover')}
						oncancel={() => handleCancel('discover')}
					/>
					<ActivityLog entries={$discoveryLog} />
				{:else}
					<DiscoverButton status={discoverStatus} onclick={handleDiscover} />
				{/if}
				{#if $discoveryStatus === 'cancelled'}
					<p class="note-text">Task discovery was cancelled.</p>
				{:else if $discoveryStatus === 'error'}
					<p class="error-text">
						Task discovery failed{$discoveryError ? `: ${$discoveryError}` : '.'} Check the activity log and try again.
					</p>
				{/if}
				{#if $discoveryStatus === 'processing' || $discoveryStatus === 'complete' || $discoveryStatus === 'error'}
					<DiscoveryProgress
						currentStage={$discoveryStage}
						progress={$discoveryProgress}
						status={$discoveryStatus}
					/>
					<ActivityLog entries={$discoveryLog} />
				{/if}
				{#if $discoveryStatus === 'processing' && discoverToken}
					<div class="job-controls">
						{#if controlError.discover}
							<p class="error-text" role="alert">{controlError.discover}</p>
						{/if}
						{#if cancelRequested.discover}
							<p class="note-text">Cancel requested. Discovery stops at the next stage boundary.</p>
						{:else}
							<button type="button" class="btn-quiet" onclick={() => handleCancel('discover')} disabled={controlBusy.discover}>
								{controlBusy.discover ? 'Cancelling...' : 'Cancel discovery'}
							</button>
						{/if}
					</div>
				{/if}
				{#if $discoveryStatus === 'complete'}
					<a href="/tasks" class="review-link" data-sveltekit-preload-data>Review Task Tree</a>
				{/if}
			</div>
		{:else if $processingStatus === 'processing'}
			<!-- Processing state: progress display replaces upload zone -->
			<div class="upload-content">
				<ProgressDisplay
					progress={$progressPct}
					currentStage={$currentStage}
					status="processing"
				/>
				<ActivityLog entries={$activityLog} expanded={activityExpanded} />
				{#if $sseState === 'reconnecting'}
					<p class="reconnecting-text">Connection lost. Reconnecting...</p>
				{/if}
				<ProcessButton onclick={handleProcess} disabled={true} status="processing" />
				{#if processToken}
					<div class="job-controls">
						{#if controlError.process}
							<p class="error-text" role="alert">{controlError.process}</p>
						{/if}
						{#if cancelRequested.process}
							<p class="note-text">Cancel requested. Processing stops at the next stage boundary.</p>
						{:else}
							<button type="button" class="btn-quiet" onclick={() => handleCancel('process')} disabled={controlBusy.process}>
								{controlBusy.process ? 'Cancelling...' : 'Cancel processing'}
							</button>
						{/if}
					</div>
				{/if}
				<FileListView {files} />
			</div>
		{:else if $processingStatus === 'paused' && $processingPause}
			<!-- Paused state: the job waits for a key or a higher spend cap -->
			<div class="upload-content">
				<ProgressDisplay
					progress={$progressPct}
					currentStage={$currentStage}
					status="paused"
				/>
				<JobPausedPanel
					jobLabel="Processing"
					reason={$processingPause}
					detail={$processingError}
					canControl={!!processToken}
					{keyHeld}
					busy={controlBusy.process}
					error={controlError.process}
					oncontinue={() => continuePaused('process')}
					oncancel={() => handleCancel('process')}
				/>
				<ActivityLog entries={$activityLog} expanded={activityExpanded} />
				<FileListView {files} />
			</div>
		{:else}
			<!-- Idle / Error state: upload zone, process button, file list -->
			<div class="upload-content">
				<UploadZone onfiles={handleFiles} disabled={uploading} />
				<ProcessButton
					onclick={handleProcess}
					disabled={files.length === 0 || uploading}
					status={$processingStatus}
				/>
				{#if $processingStatus === 'cancelled'}
					<p class="note-text">Processing was cancelled. You can start it again.</p>
				{/if}
				{#if $processingStatus === 'error' && $processingError}
					<p class="error-text">
						Processing failed. Check the activity log for details and retry.
					</p>
					<ActivityLog entries={$activityLog} expanded={true} />
				{/if}
				<FileListView {files} onremove={handleRemoveFile} />
			</div>
		{/if}

		<LLMJobDialog
			open={dialog.open}
			mode={dialog.mode}
			title={dialogTitle}
			intro={dialogIntro}
			confirmLabel={dialogConfirm}
			onsubmit={runDialog}
			onclose={() => (dialog = { ...dialog, open: false })}
		/>

		<!-- Screen reader announcements -->
		<div aria-live="polite" class="sr-only">{statusAnnouncement}</div>
	</div>
</div>

<style>
	.upload-layout {
		display: flex;
		height: 100%;
	}

	.upload-main {
		flex: 1;
		padding: var(--md);
		overflow-y: auto;
	}

	.upload-content {
		display: flex;
		flex-direction: column;
		gap: var(--md);
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

	.success-text {
		font-size: 14px;
		color: var(--green);
		text-align: center;
		padding: var(--md) 0;
	}

	.error-text {
		font-size: 13px;
		color: var(--red);
	}

	.note-text {
		font-size: 13px;
		color: var(--text-dim);
	}

	.job-controls {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--xs);
	}

	.btn-quiet {
		height: 32px;
		padding: 0 var(--md);
		font-size: 13px;
		border-radius: 4px;
		color: var(--text-dim);
		border: 1px solid var(--border);
		transition: color 150ms ease;
	}

	.btn-quiet:hover:not(:disabled) {
		color: var(--text);
	}

	.btn-quiet:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.reconnecting-text {
		font-size: 11px;
		color: var(--orange);
	}

	.review-link {
		font-size: 14px;
		font-weight: 600;
		color: var(--accent);
		text-decoration: none;
		text-align: center;
		padding: var(--sm) 0;
	}

	.review-link:hover {
		text-decoration: underline;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
</style>
