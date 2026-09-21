/**
 * Prefab wire-format types (prefab_ui 0.18.0, PROTOCOL_VERSION "0.2").
 *
 * Captured from real `PrefabApp.to_json()` output - NOT guessed. The plan
 * (mcp-central-docs/archive/fastmcp/prefab-web-renderer-scaffold-plan.md)
 * Phase 1 explicitly warns against inferring field names from Python.
 *
 * Confirmed facts:
 *   - discriminant is `type` (component class name), e.g. "Card", "Metric"
 *   - children live in `children` (array), recursively
 *   - text lives in `content` (H2 / P / CardTitle / CardDescription)
 *   - Badge uses `label` (NOT `content`), plus `variant`
 *   - Metric uses `label` + `value`
 *   - props are camelCase (`cssClass`); None-valued props are omitted
 *   - envelope is `{ "$prefab": { "version": "0.2" }, "view": {...} }`
 *
 * Ground-truth fixtures: ./fixtures.ts
 */

export interface PrefabNode {
	type?: string;
	children?: PrefabNode[];
	content?: string;
	label?: string;
	value?: string;
	variant?: string;
	orientation?: string;
	src?: string;
	alt?: string;
	width?: string;
	height?: string;
	cssClass?: string;
	[key: string]: unknown;
}

export interface PrefabEnvelope {
	$prefab?: { version?: string };
	view?: PrefabNode;
	state?: Record<string, unknown> | null;
	defs?: unknown;
	theme?: unknown;
}

/** One tool call's card, as returned by the backend under `prefabs[]`. */
export interface PrefabPayload {
	tool?: string;
	prefab?: PrefabEnvelope | null;
}

/**
 * Narrow untrusted server data to a Prefab envelope.
 * Returns null rather than throwing - the renderer must never crash on
 * malformed payloads.
 */
export function asPrefabEnvelope(raw: unknown): PrefabEnvelope | null {
	if (!raw || typeof raw !== "object") return null;
	const env = raw as PrefabEnvelope;
	if (!env.view || typeof env.view !== "object") return null;
	return env;
}
