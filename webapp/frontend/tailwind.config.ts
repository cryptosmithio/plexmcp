import type { Config } from "tailwindcss";

const config: Config = {
	content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
	// Prefab cards arrive as server JSON at runtime, so their Tailwind classes
	// never appear in source and would otherwise be purged from the build.
	// Safelist the layout utilities the Prefab card builders emit - see
	// components/prefab/prefab-renderer.tsx.
	safelist: [
		{ pattern: /^grid-cols-[1-6]$/, variants: ["sm", "md", "lg", "xl", "2xl"] },
		{ pattern: /^(gap|my|mt|mb)-[0-8]$/ },
	],
	theme: {
		extend: {
			colors: {
				background: "var(--background)",
				foreground: "var(--foreground)",
				// Do not set `slate` or `amber` to a single hex string here: that replaces the
				// entire default color scale and breaks utilities like `text-slate-100`,
				// `bg-slate-800`, `border-amber-800` (appears as a blank / “black” UI).
			},
		},
	},
	plugins: [],
};
export default config;
