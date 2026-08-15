import { useCallback, useEffect, useState } from "react";

import { commercialRequest } from "./commercial-auth";

export type PriceRow = { model: string; quality: string; credits: number };
export type PricingTable = Record<string, Record<string, number>>;

/** 图片质量档 → 价格表 quality 键（与后端 pricing_quality 对齐）。 */
const IMAGE_QUALITY_TO_PRICE_KEY: Record<string, string> = {
    auto: "auto",
    low: "low",
    standard: "low",
    medium: "medium",
    high: "high",
    hd: "medium",
    "1k": "low",
    "2k": "medium",
    "4k": "high",
};

/** 视频清晰度 → 价格表 quality 键。 */
const VIDEO_QUALITY_TO_PRICE_KEY: Record<string, string> = {
    "480p": "480p",
    "720p": "720p",
    "1080p": "1080p",
    "2k": "2K",
    low: "480p",
    medium: "720p",
    high: "2K",
    hd: "720p",
    auto: "720p",
};

function toTable(rows: PriceRow[]): PricingTable {
    const table: PricingTable = {};
    for (const row of rows) {
        if (!table[row.model]) table[row.model] = {};
        table[row.model][row.quality] = row.credits;
    }
    return table;
}

export function usePricing() {
    const [table, setTable] = useState<PricingTable>({});
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        commercialRequest<{ prices: PriceRow[] }>("/api/catalog/pricing")
            .then((data) => {
                if (!cancelled) setTable(toTable(data.prices || []));
            })
            .catch(() => {
                /* 未登录或加载失败时不展示积分预估 */
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    /** 图片预计积分：model + 质量档 × 张数。 */
    const estimateImageCredits = useCallback(
        (model: string, quality: string, count: number) => {
            const priceKey = IMAGE_QUALITY_TO_PRICE_KEY[(quality || "auto").toLowerCase()] || "auto";
            const perImage = table[model]?.[priceKey] ?? table[model]?.["low"] ?? table[model]?.["auto"];
            if (perImage == null) return null;
            return perImage * Math.max(1, Math.min(15, Math.floor(Math.abs(Number(count)) || 1)));
        },
        [table],
    );

    /** 视频预计积分：model + 清晰度档的每秒单价 × 时长。 */
    const estimateVideoCredits = useCallback(
        (model: string, videoQuality: string, duration: number) => {
            const priceKey = VIDEO_QUALITY_TO_PRICE_KEY[(videoQuality || "720p").toLowerCase()] || "720p";
            const perSecond = table[model]?.[priceKey];
            if (perSecond == null) return null;
            const seconds = Math.max(1, Math.min(15, Math.floor(Math.abs(Number(duration)) || 5)));
            return perSecond * seconds;
        },
        [table],
    );

    return { pricing: table, pricingLoading: loading, estimateImageCredits, estimateVideoCredits };
}
