"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { MediaDetailClient } from "./media-detail-client";

function MediaPageInner() {
	const searchParams = useSearchParams();
	const ratingKey = searchParams?.get("ratingKey") ?? "";

	if (!ratingKey) {
		return (
			<div className="max-w-3xl mx-auto p-6">
				<p className="text-slate-400">
					No rating key given. Open a media dossier from a movie's "Full dossier" link, or from the
					Enrichment page.
				</p>
			</div>
		);
	}

	return <MediaDetailClient ratingKey={ratingKey} />;
}

export default function MediaPage() {
	return (
		<Suspense fallback={<div className="p-6 text-slate-400">Loading…</div>}>
			<MediaPageInner />
		</Suspense>
	);
}
