<script lang="ts">
	export interface AnnotationSpan {
		id: string;
		/** Half-open canonical source character offsets (Unicode code points). */
		start: number;
		end: number;
		label?: string;
	}
	let { text, spans = [] }: { text: string; spans?: AnnotationSpan[] } = $props();

	let segments = $derived.by(() => {
		const characters = Array.from(text);
		const events = new Map<number, { starts: AnnotationSpan[]; ends: AnnotationSpan[] }>();
		function at(offset: number) {
			if (!events.has(offset)) events.set(offset, { starts: [], ends: [] });
			return events.get(offset)!;
		}
		at(0);
		at(characters.length);
		for (const span of spans) {
			if (!Number.isInteger(span.start) || !Number.isInteger(span.end)
				|| span.start < 0 || span.end > characters.length || span.start >= span.end) continue;
			at(span.start).starts.push(span);
			at(span.end).ends.push(span);
		}
		const boundaries = [...events.keys()].sort((a, b) => a - b);
		const active = new Set<AnnotationSpan>();
		const result = [];
		for (let i = 0; i < boundaries.length - 1; i++) {
			const start = boundaries[i];
			const end = boundaries[i + 1];
			const event = events.get(start)!;
			for (const span of event.ends) active.delete(span);
			for (const span of event.starts) active.add(span);
			result.push({
				start, end, text: characters.slice(start, end).join(''),
				ids: [...active].map((span) => span.id).join(' '),
				label: [...active].map((span) => span.label ?? span.id).join('; '),
			});
		}
		return result;
	});
</script>

<span class="annotated-text">{#each segments as segment (segment.start)}{#if segment.ids}<mark data-annotation-ids={segment.ids} data-start={segment.start} data-end={segment.end} title={segment.label}>{segment.text}</mark>{:else}{segment.text}{/if}{/each}</span>

<style>
	.annotated-text {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font: 21px/1.8 var(--reading);
		color: var(--paper);
	}
	mark { background: var(--highlight); color: inherit; border-bottom: 2px solid var(--accent); }
</style>
