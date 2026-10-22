// Image presets adapted from infinite-canvas v0.20.0 (AGPL-3.0), lib/media-size.ts.
export const imageSizePresets: Record<string, Record<string, string>> = {
    low: { "1:1": "1024x1024", "2:3": "1024x1536", "3:2": "1536x1024", "4:3": "1024x768", "3:4": "768x1024", "16:9": "1536x864", "9:16": "864x1536", "21:9": "2016x864", "9:21": "864x2016" },
    medium: { "1:1": "2048x2048", "2:3": "1360x2048", "3:2": "2048x1360", "4:3": "2048x1536", "3:4": "1536x2048", "16:9": "2048x1152", "9:16": "1152x2048", "21:9": "2688x1152", "9:21": "1152x2688" },
    high: { "1:1": "2880x2880", "2:3": "2336x3520", "3:2": "3520x2336", "4:3": "3312x2480", "3:4": "2480x3312", "16:9": "3840x2160", "9:16": "2160x3840", "21:9": "3840x1648", "9:21": "1648x3840" },
};

export function imageQualityForSize(size: string) {
    const preset = Object.keys(imageSizePresets).find((quality) => Object.values(imageSizePresets[quality]).includes(size.toLowerCase()));
    if (preset) return preset;
    const match = size.match(/^(\d+)x(\d+)$/i);
    if (!match) return "auto";
    const edge = Math.max(Number(match[1]), Number(match[2]));
    return edge >= 3072 ? "high" : edge >= 2048 ? "medium" : "low";
}

export function resolveImageQuality(quality: string, size: string) {
    const aliases: Record<string, string> = { "1k": "low", "2k": "medium", "4k": "high", standard: "low", hd: "medium" };
    const normalized = aliases[quality.toLowerCase()] || quality.toLowerCase() || "auto";
    const inferred = imageQualityForSize(size);
    const rank = ["auto", "low", "medium", "high"];
    return rank.indexOf(inferred) > rank.indexOf(normalized) ? inferred : normalized;
}

export function imageAspectRatio(size: string) {
    if (!size || size === "auto") return "auto";
    const match = size.match(/^(\d+)[x:](\d+)$/i);
    if (!match) return "1:1";
    const target = Number(match[1]) / Number(match[2]);
    return Object.keys(imageSizePresets.low).reduce((best, ratio) => {
        const [w, h] = ratio.split(":").map(Number);
        const [bw, bh] = best.split(":").map(Number);
        return Math.abs(w / h - target) < Math.abs(bw / bh - target) ? ratio : best;
    }, "1:1");
}

export function imageSizeForQuality(quality: string, ratio: string) {
    if (ratio === "auto") return "auto";
    return imageSizePresets[quality]?.[ratio] || ratio;
}
