"use client";

/**
 * Dev-only preview for the Prefab renderer.
 *
 * Renders the ground-truth fixtures from `components/prefab/fixtures.ts` so the
 * renderer can be exercised in a browser without a live Plex server. This is
 * the "Phase 4" preview route from the deferred plan
 * (mcp-central-docs/archive/fastmcp/prefab-web-renderer-scaffold-plan.md).
 *
 * No backend calls, no data access - static fixtures only.
 */

import { ALL_FIXTURES } from "@/components/prefab/fixtures";
import { PrefabRenderer } from "@/components/prefab/prefab-renderer";

export default function DevPrefabPage() {
	return (
		<div className="container mx-auto p-6 space-y-8" data-testid="dev-prefab-page">
			<div>
				<h1 className="text-xl font-semibold text-zinc-100">Prefab renderer preview</h1>
				<p className="text-sm text-zinc-400 mt-1">
					Ground-truth fixtures from <code>components/prefab/fixtures.ts</code>. If a card below
					renders empty, upstream <code>prefab_ui</code> serialization changed.
				</p>
			</div>

			{ALL_FIXTURES.map(({ name, envelope }) => (
				<section key={name} className="space-y-2">
					<h2 className="text-sm font-mono text-zinc-500">{name}</h2>
					<PrefabRenderer envelope={envelope} />
				</section>
			))}
		</div>
	);
}
