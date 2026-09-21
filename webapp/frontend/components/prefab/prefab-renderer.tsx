"use client";

/**
 * Minimal Prefab renderer for the Plex webapp.
 *
 * Prefab is a Python DSL that serializes to a JSON component tree
 * (`prefab_ui`, PROTOCOL_VERSION "0.2"). MCP hosts such as Claude Desktop ship
 * a React runtime for it; a plain browser does not. This renders the subset of
 * components that plex-mcp's card builders actually emit, so a tool call made
 * in the webapp chat can show the same card the chat client shows.
 *
 * Scope (deliberately narrow - see the deferred plan in mcp-central-docs):
 *   Div, Row, Grid, Card, CardHeader, CardTitle, CardDescription, CardContent,
 *   H2, H3, H4, P, Text, Small, Metric, Badge, Separator, Image.
 *   Unknown types fall through to their children rather than vanishing.
 *
 * Non-goals: interactive actions, state binding, DataTable, theme parity.
 */

import type { ReactNode } from "react";
import { type PrefabEnvelope, type PrefabNode, asPrefabEnvelope } from "./prefab-types";

/**
 * `pf-app-root` is Prefab's theme hook (targets `.pf-app-root` for app-level
 * padding/background). This app has no Prefab theme, so it is stripped to avoid
 * a dead class. Remaining classes are Tailwind utilities, safelisted in
 * tailwind.config.ts because they arrive from the server at runtime and would
 * otherwise be purged from the build.
 */
function classes(node: PrefabNode): string {
	return (node.cssClass ?? "")
		.split(/\s+/)
		.filter((c) => c && c !== "pf-app-root")
		.join(" ");
}

function text(value: unknown): string {
	return value == null ? "" : String(value);
}

const BADGE_VARIANTS: Record<string, string> = {
	success: "border-green-600/40 bg-green-500/20 text-green-300",
	destructive: "border-red-600/40 bg-red-500/20 text-red-300",
	info: "border-sky-600/40 bg-sky-500/20 text-sky-300",
	warning: "border-amber-600/40 bg-amber-500/20 text-amber-300",
	secondary: "border-zinc-500/40 bg-zinc-600/40 text-zinc-300",
};

function renderNode(node: PrefabNode | null | undefined, key: number): ReactNode {
	if (!node || typeof node !== "object") return null;

	const kids = Array.isArray(node.children) ? node.children : [];
	const children = kids.map((child, i) => renderNode(child, i));
	const cls = classes(node);

	switch (node.type) {
		case "Div":
			return (
				<div key={key} className={cls || "space-y-3"}>
					{children}
				</div>
			);
		case "Row":
			return (
				<div key={key} className={`flex flex-wrap items-center gap-3 ${cls}`}>
					{children}
				</div>
			);
		case "Grid":
			return (
				<div key={key} className={`grid ${cls || "grid-cols-1 gap-4 md:grid-cols-2"}`}>
					{children}
				</div>
			);
		case "Card":
			return (
				<div key={key} className={`rounded-lg border border-zinc-600/60 bg-zinc-800/60 p-4 ${cls}`}>
					{children}
				</div>
			);
		case "CardHeader":
			return (
				<div key={key} className={`mb-2 ${cls}`}>
					{children}
				</div>
			);
		case "CardTitle":
			return (
				<h3 key={key} className={`font-semibold text-zinc-100 ${cls}`}>
					{text(node.content)}
				</h3>
			);
		case "CardDescription":
			return (
				<p key={key} className={`text-xs text-zinc-400 ${cls}`}>
					{text(node.content)}
				</p>
			);
		case "CardContent":
			return (
				<div key={key} className={cls}>
					{children}
				</div>
			);
		case "H2":
			return (
				<h2 key={key} className={`text-lg font-semibold text-zinc-100 ${cls}`}>
					{text(node.content)}
				</h2>
			);
		case "H3":
			return (
				<h3 key={key} className={`text-base font-semibold text-zinc-100 ${cls}`}>
					{text(node.content)}
				</h3>
			);
		case "H4":
			return (
				<h4 key={key} className={`text-sm font-semibold text-zinc-200 ${cls}`}>
					{text(node.content)}
				</h4>
			);
		case "P":
			return (
				<p key={key} className={`text-sm text-zinc-300 ${cls}`}>
					{text(node.content)}
				</p>
			);
		case "Text":
		case "Small":
			return (
				<span key={key} className={`text-xs text-zinc-400 ${cls}`}>
					{text(node.content)}
				</span>
			);
		case "Metric":
			return (
				<div key={key} className={`rounded-md bg-zinc-900/50 px-3 py-2 ${cls}`}>
					<div className="text-[11px] uppercase tracking-wide text-zinc-500">
						{text(node.label)}
					</div>
					<div className="text-sm font-medium text-zinc-100">{text(node.value)}</div>
				</div>
			);
		case "Badge":
			return (
				<span
					key={key}
					className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${
						BADGE_VARIANTS[String(node.variant)] ?? BADGE_VARIANTS.secondary
					} ${cls}`}
				>
					{text(node.label)}
				</span>
			);
		case "Separator":
			if (node.orientation === "vertical") {
				return <span key={key} className={`mx-2 inline-block h-4 w-px bg-zinc-600 ${cls}`} />;
			}
			return <hr key={key} className={`my-3 border-zinc-700 ${cls}`} />;
		case "Image":
			// src arrives from the server payload; next/image needs known dimensions.
			return (
				<img
					key={key}
					src={text(node.src)}
					alt={text(node.alt)}
					style={{ width: node.width, height: node.height }}
					className={`rounded ${cls}`}
				/>
			);
		default:
			// Unknown component - render its children so content is never lost.
			return (
				<div key={key} className={cls}>
					{children}
				</div>
			);
	}
}

export function PrefabRenderer({ envelope }: { envelope: unknown }) {
	const env = asPrefabEnvelope(envelope);
	if (!env?.view) return null;

	return (
		<div
			className="rounded-lg border border-zinc-600/60 bg-zinc-900/40 p-3"
			data-testid="prefab-card"
		>
			{renderNode(env.view, 0)}
		</div>
	);
}

export default PrefabRenderer;
