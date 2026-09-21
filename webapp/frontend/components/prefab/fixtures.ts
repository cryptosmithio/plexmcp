/**
 * Ground-truth Prefab fixtures.
 *
 * These are verbatim `PrefabApp.to_json()` output from plex-mcp's own card
 * builders (`src/plex_mcp/prefabs.py`, prefab_ui 0.18.0). They exist so the
 * renderer can be exercised in a browser without a live Plex server, and so
 * upstream serialization changes fail visibly instead of silently.
 *
 * Regenerate with a probe that prints `app.to_json()` for each builder.
 */

import type { PrefabEnvelope } from "./prefab-types";

export const LIBRARY_GRID_FIXTURE: PrefabEnvelope = {
	$prefab: { version: "0.2" },
	view: {
		cssClass: "pf-app-root",
		type: "Div",
		children: [
			{ content: "Media Libraries", type: "H2" },
			{ content: "All configured Plex library sections.", type: "P" },
			{ cssClass: "my-4", type: "Separator", orientation: "horizontal" },
			{
				cssClass: "gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3",
				type: "Grid",
				children: [
					{
						type: "Card",
						children: [
							{
								type: "CardHeader",
								children: [
									{ type: "CardTitle", content: "Movies" },
									{ type: "CardDescription", content: "Type: movie" },
								],
							},
							{
								type: "CardContent",
								children: [{ type: "Metric", label: "Items", value: "120" }],
							},
						],
					},
				],
			},
		],
	},
};

export const SERVER_STATUS_FIXTURE: PrefabEnvelope = {
	$prefab: { version: "0.2" },
	view: {
		cssClass: "pf-app-root",
		type: "Div",
		children: [
			{
				type: "Row",
				children: [
					{ content: "Server Status", type: "H2" },
					{ type: "Badge", label: "Online", variant: "success" },
				],
			},
			{ cssClass: "my-4", type: "Separator", orientation: "horizontal" },
			{
				cssClass: "gap-4 grid-cols-2 md:grid-cols-4",
				type: "Grid",
				children: [
					{ type: "Metric", label: "Version", value: "1.41.0" },
					{ type: "Metric", label: "Uptime", value: "3 days" },
					{ type: "Metric", label: "Active Sessions", value: "2" },
					{ type: "Metric", label: "Libraries", value: "4" },
				],
			},
		],
	},
};

export const ALL_FIXTURES: Array<{ name: string; envelope: PrefabEnvelope }> = [
	{ name: "library_grid", envelope: LIBRARY_GRID_FIXTURE },
	{ name: "server_status", envelope: SERVER_STATUS_FIXTURE },
];
