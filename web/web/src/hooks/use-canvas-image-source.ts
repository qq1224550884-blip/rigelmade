import { useEffect, useState } from "react";
import { ensureImagePreview } from "@/services/image-storage";
import { PREVIEW_EDGE } from "@/lib/image-thumbnail";

export function useCanvasImageSource(storageKey: string | undefined, original: string, renderedEdge: number) {
    const [preview, setPreview] = useState<{ key: string; url: string } | null>(null);
    useEffect(() => {
        let active = true;
        if (storageKey) void ensureImagePreview(storageKey).then((url) => { if (active && url) setPreview({ key: storageKey, url }); });
        return () => { active = false; };
    }, [storageKey, original]);
    return renderedEdge * (window.devicePixelRatio || 1) <= PREVIEW_EDGE && preview && preview.key === storageKey ? preview.url : original;
}
