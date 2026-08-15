import { useMemo } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { nanoid } from "nanoid";

export type ApiCallFormat = "openai" | "gemini" | "ark";
export type ModelCapability = "image" | "video" | "text" | "audio";
export type ReasoningEffort = "auto" | "low" | "medium" | "high" | "xhigh";

export type ChannelModel = {
    name: string;
    capability: ModelCapability;
    script?: string;
};

export type ModelChannel = {
    id: string;
    name: string;
    baseUrl: string;
    apiKey: string;
    apiFormat: ApiCallFormat;
    models: ChannelModel[];
};

export type AiConfig = {
    channelMode: "remote" | "local";
    baseUrl: string;
    apiKey: string;
    apiFormat: ApiCallFormat;
    channels: ModelChannel[];
    model: string;
    imageModel: string;
    videoModel: string;
    textModel: string;
    audioModel: string;
    audioVoice: string;
    audioFormat: string;
    audioSpeed: string;
    audioInstructions: string;
    videoSeconds: string;
    vquality: string;
    videoGenerateAudio: string;
    videoWatermark: string;
    systemPrompt: string;
    reasoningEffort: ReasoningEffort;
    models: string[];
    quality: string;
    size: string;
    background: string;
    count: string;
    canvasImageCount: string;
};

export type WebdavSyncConfig = {
    url: string;
    username: string;
    password: string;
    directory: string;
    lastSyncedAt: string;
};
export type ConfigTabKey = "channels" | "preferences" | "prompt-sources" | "webdav";

export const CONFIG_STORE_KEY = "infinite-canvas:ai_config_store";
const CHANNEL_MODEL_SEPARATOR = "::";
const OPENAI_BASE_URL = "https://api.openai.com";
const GEMINI_BASE_URL = "https://generativelanguage.googleapis.com";
const ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3";
const LOCAL_WORKBENCH_CHANNEL_ID = "grsai-default";
// `banana-fast` was an early fixed local proxy.  Keep its id only so that
// saved browser settings can be migrated into an editable direct channel.
const LEGACY_FAST_BANANA_CHANNEL_ID = "banana-fast";
const LOCAL_WORKBENCH_BASE_URL = typeof window === "undefined"
    ? "http://127.0.0.1:8790"
    : window.location.origin;
const LOCAL_WORKBENCH_MODELS: ChannelModel[] = [
    { name: "gpt-image-2", capability: "image" },
    { name: "nano-banana-2", capability: "image" },
    { name: "nano-banana-fast", capability: "image" },
    { name: "nano-banana-pro", capability: "image" },
];
// pdhlzy 的 Nano Banana 不是 /images/generations 协议：它需要 OpenAI
// chat/completions、Gemini 上游模型名，以及 google.image_config。脚本公开显示在
// 渠道编辑器中，用户可根据自己中转站的文档修改；调用时浏览器直接访问中转站。
const DIRECT_BANANA_SCRIPT = [
    'const upstreamModel = model === "nano-banana-2" ? "gemini-3.1-flash-image-preview" : model === "nano-banana-pro" ? "gemini-3-pro-image-preview" : model;',
    'const imageSize = params.quality === "high" ? "4K" : params.quality === "medium" ? "2K" : "1K";',
    'const ratios = ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "1:8", "8:1", "1:4", "4:1"];',
    'const match = String(params.size || "").match(/^(\\d+)x(\\d+)$/i);',
    'const target = match ? Number(match[1]) / Number(match[2]) : 1;',
    'const aspectRatio = ratios.reduce((best, value) => { const [w, h] = value.split(":").map(Number); const [bw, bh] = best.split(":").map(Number); return Math.abs(w / h - target) < Math.abs(bw / bh - target) ? value : best; }, "1:1");',
    'const content = [{ type: "text", text: prompt }, ...images.map((url) => ({ type: "image_url", image_url: { url } }))];',
    'const data = await request({ method: "post", url: `${baseUrl}/v1/chat/completions`, headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` }, data: { model: upstreamModel, messages: [{ role: "user", content }], stream: false, extra_body: { google: { image_config: { image_size: imageSize, aspect_ratio: aspectRatio } } } } });',
    'const source = data.choices?.[0]?.message?.content ?? data.choices?.[0]?.message ?? data;',
    'const urls = []; const seen = new Set();',
    'const add = (value) => { if (typeof value !== "string") return; for (const item of value.matchAll(/data:image\\/[-\\w.+]+;base64,[A-Za-z0-9+/=\\r\\n]+|https?:\\/\\/[^\\s)\\]"\'<>,]+/g)) { const url = item[0].replace(/[.,]+$/, ""); if (!seen.has(url)) { seen.add(url); urls.push(url); } } };',
    'const walk = (value) => { if (typeof value === "string") { add(value); return; } if (Array.isArray(value)) { value.forEach(walk); return; } if (value && typeof value === "object") Object.values(value).forEach(walk); };',
    'walk(source); if (!urls.length) throw new Error("中转站没有返回图片数据"); return urls;',
].join("\n");
const DIRECT_BANANA_MODELS: ChannelModel[] = [
    { name: "nano-banana-2", capability: "image", script: DIRECT_BANANA_SCRIPT },
    { name: "nano-banana-pro", capability: "image", script: DIRECT_BANANA_SCRIPT },
];

function localWorkbenchChannel(): ModelChannel {
    let token = "";
    if (typeof window !== "undefined") {
        try { token = JSON.parse(localStorage.getItem("ai-render-commercial:session") || "null")?.token || ""; } catch { token = ""; }
    }
    return {
        id: LOCAL_WORKBENCH_CHANNEL_ID,
        name: "本机",
        baseUrl: LOCAL_WORKBENCH_BASE_URL,
        apiKey: token || "commercial-login-required",
        apiFormat: "openai",
        models: LOCAL_WORKBENCH_MODELS.map((model) => ({ ...model })),
    };
}

function directBananaChannel(): ModelChannel {
    return {
        id: LEGACY_FAST_BANANA_CHANNEL_ID,
        name: "快速渠道",
        baseUrl: "https://pdhlzy.com",
        apiKey: "",
        apiFormat: "openai",
        models: DIRECT_BANANA_MODELS.map((model) => ({ ...model })),
    };
}

export const defaultConfig: AiConfig = {
    channelMode: "local",
    baseUrl: OPENAI_BASE_URL,
    apiKey: "",
    apiFormat: "openai",
    channels: [
        localWorkbenchChannel(),
        directBananaChannel(),
    ],
    model: "grsai-default::gpt-image-2",
    imageModel: "grsai-default::gpt-image-2",
    videoModel: "grsai-default::gpt-image-2",
    textModel: "grsai-default::gpt-image-2",
    audioModel: "grsai-default::gpt-image-2",
    audioVoice: "alloy",
    audioFormat: "mp3",
    audioSpeed: "1",
    audioInstructions: "",
    videoSeconds: "6",
    vquality: "720",
    videoGenerateAudio: "true",
    videoWatermark: "false",
    systemPrompt: "",
    reasoningEffort: "auto",
    models: [
        "grsai-default::gpt-image-2",
        "grsai-default::nano-banana-2",
        "grsai-default::nano-banana-fast",
        "grsai-default::nano-banana-pro",
        "banana-fast::nano-banana-2",
        "banana-fast::nano-banana-pro",
    ],
    quality: "auto",
    size: "1:1",
    background: "",
    count: "1",
    canvasImageCount: "3",
};

export const defaultWebdavSyncConfig: WebdavSyncConfig = {
    url: "",
    username: "",
    password: "",
    directory: "infinite-canvas",
    lastSyncedAt: "",
};

type ConfigStore = {
    config: AiConfig;
    webdav: WebdavSyncConfig;
    isConfigOpen: boolean;
    configTab: ConfigTabKey;
    shouldPromptContinue: boolean;
    updateConfig: <K extends keyof AiConfig>(key: K, value: AiConfig[K]) => void;
    updateWebdavConfig: <K extends keyof WebdavSyncConfig>(key: K, value: WebdavSyncConfig[K]) => void;
    isAiConfigReady: (config: AiConfig, model: string) => boolean;
    openConfigDialog: (shouldPromptContinue?: boolean, tab?: ConfigTabKey) => void;
    setConfigDialogOpen: (isOpen: boolean) => void;
    clearPromptContinue: () => void;
};

const VIDEO_KEYWORDS = ["seedance", "video", "sora", "veo", "kling", "wan", "hailuo"];
const AUDIO_KEYWORDS = ["audio", "tts", "speech", "voice", "music", "sound"];
const IMAGE_KEYWORDS = ["seedream", "gpt-image", "image", "dall-e", "dalle", "imagen", "banana", "flux", "sdxl", "stable-diffusion", "midjourney"];

/** Best-effort default capability for a freshly fetched model name; user can override in the channel editor. */
export function guessCapability(name: string): ModelCapability {
    const value = name.toLowerCase();
    if (VIDEO_KEYWORDS.some((keyword) => value.includes(keyword))) return "video";
    if (AUDIO_KEYWORDS.some((keyword) => value.includes(keyword))) return "audio";
    if (IMAGE_KEYWORDS.some((keyword) => value.includes(keyword))) return "image";
    return "text";
}

function findChannelModel(config: AiConfig, value: string): { channel: ModelChannel; model: ChannelModel } | null {
    const decoded = decodeChannelModel(value);
    const name = decoded?.model || value;
    const channel = decoded ? config.channels.find((item) => item.id === decoded.channelId) : config.channels.find((item) => item.models.some((model) => model.name === name));
    const model = channel?.models.find((item) => item.name === name);
    return channel && model ? { channel, model } : null;
}

export function modelCapabilityOf(config: AiConfig, value: string): ModelCapability | undefined {
    return findChannelModel(config, value)?.model.capability;
}

export function modelMatchesCapability(config: AiConfig, value: string, capability?: ModelCapability) {
    if (!capability) return true;
    return modelCapabilityOf(config, value) === capability;
}

export function resolveModelForCapability(config: AiConfig, currentModel: string | undefined, capability: ModelCapability) {
    const defaultModel = capability === "image" ? config.imageModel : capability === "video" ? config.videoModel : capability === "audio" ? config.audioModel : config.textModel;
    const fallbackModel = capability === "image" ? defaultConfig.imageModel : capability === "video" ? defaultConfig.videoModel : capability === "audio" ? defaultConfig.audioModel : defaultConfig.textModel;
    if (currentModel && modelMatchesCapability(config, currentModel, capability)) return currentModel;
    if (defaultModel && modelMatchesCapability(config, defaultModel, capability)) return defaultModel;
    return fallbackModel;
}

export function selectableModelsByCapability(config: AiConfig, capability?: ModelCapability) {
    if (!capability) return config.models;
    return config.channels.flatMap((channel) => channel.models.filter((model) => model.capability === capability).map((model) => encodeChannelModel(channel.id, model.name)));
}

/** The user script (if any) attached to a model; empty string means use the system default call. */
export function resolveModelScript(config: AiConfig, value: string) {
    return findChannelModel(config, value)?.model.script?.trim() || "";
}

function isAiConfigReady(config: AiConfig, model: string) {
    const channel = resolveModelChannel(config, model);
    return Boolean(model.trim() && channel.baseUrl.trim() && channel.apiKey.trim());
}

export const useConfigStore = create<ConfigStore>()(
    persist(
        (set, get) => ({
            config: defaultConfig,
            webdav: defaultWebdavSyncConfig,
            isConfigOpen: false,
            configTab: "channels",
            shouldPromptContinue: false,
            updateConfig: (key, value) =>
                set((state) => ({
                    config: {
                        ...state.config,
                        [key]: value,
                    },
                })),
            updateWebdavConfig: (key, value) =>
                set((state) => ({
                    webdav: {
                        ...state.webdav,
                        [key]: value,
                    },
                })),
            isAiConfigReady: (config, model) => isAiConfigReady(config, model),
            openConfigDialog: (shouldPromptContinue = false, configTab = "channels") => set({ isConfigOpen: true, shouldPromptContinue, configTab }),
            setConfigDialogOpen: (isConfigOpen) => set({ isConfigOpen }),
            clearPromptContinue: () => set({ shouldPromptContinue: false }),
        }),
        {
            name: CONFIG_STORE_KEY,
            partialize: (state) => ({ config: state.config, webdav: state.webdav }),
            merge: (persisted, current) => {
                const persistedState = (persisted || {}) as Partial<ConfigStore>;
                const persistedConfig = (persistedState.config || {}) as Partial<AiConfig>;
                const persistedWebdav = (persistedState.webdav || {}) as Partial<WebdavSyncConfig>;
                return {
                    ...current,
                    webdav: { ...defaultWebdavSyncConfig, ...persistedWebdav },
                    config: normalizeAiConfig(persistedConfig),
                };
            },
        },
    ),
);

export function useEffectiveConfig() {
    const config = useConfigStore((state) => state.config);
    return useMemo(() => ({ ...config, channelMode: "local" as const }), [config]);
}

/** Normalize a mixed list of raw model names or model objects into deduped ChannelModel entries. */
export function normalizeChannelModels(models: Array<string | ChannelModel> | undefined): ChannelModel[] {
    const seen = new Set<string>();
    const result: ChannelModel[] = [];
    for (const item of models || []) {
        const name = (typeof item === "string" ? item : item?.name || "").trim();
        if (!name || seen.has(name)) continue;
        seen.add(name);
        const capability = typeof item === "string" ? guessCapability(name) : item.capability || guessCapability(name);
        const script = typeof item === "string" ? undefined : item.script?.trim() || undefined;
        result.push({ name, capability, script });
    }
    return result;
}

export function createModelChannel(channel?: Partial<ModelChannel>): ModelChannel {
    const apiFormat = normalizeApiFormat(channel?.apiFormat);
    return {
        id: channel?.id?.trim() || nanoid(),
        name: channel?.name?.trim() || "新渠道",
        baseUrl: channel?.baseUrl?.trim() || defaultBaseUrlForApiFormat(apiFormat),
        apiKey: channel?.apiKey || "",
        apiFormat,
        models: normalizeChannelModels(channel?.models),
    };
}

export function encodeChannelModel(channelId: string, model: string) {
    return `${channelId}${CHANNEL_MODEL_SEPARATOR}${model.trim()}`;
}

export function isChannelModelValue(value: string) {
    return value.includes(CHANNEL_MODEL_SEPARATOR);
}

export function decodeChannelModel(value: string) {
    const index = value.indexOf(CHANNEL_MODEL_SEPARATOR);
    if (index < 0) return null;
    return { channelId: value.slice(0, index), model: value.slice(index + CHANNEL_MODEL_SEPARATOR.length) };
}

export function modelOptionName(value: string) {
    return decodeChannelModel(value)?.model || value;
}

export function modelOptionLabel(config: AiConfig, value: string) {
    const decoded = decodeChannelModel(value);
    if (!decoded) return value;
    const channel = config.channels.find((item) => item.id === decoded.channelId);
    if (!channel) return decoded.model;
    const sameNameChannels = config.channels.filter((item) => item.models.some((model) => model.name === decoded.model));
    if (sameNameChannels.length <= 1) return decoded.model;
    return `${decoded.model}（${channel.name}）`;
}

export function modelOptionsFromChannels(channels: ModelChannel[]) {
    return uniqueModelOptions(channels.flatMap((channel) => channel.models.map((model) => encodeChannelModel(channel.id, model.name))));
}

export function normalizeModelOptionValue(value: string | undefined, channels: ModelChannel[]) {
    const model = (value || "").trim();
    if (!model) return "";
    const decoded = decodeChannelModel(model);
    if (decoded) {
        const channel = channels.find((item) => item.id === decoded.channelId);
        return channel && channel.models.some((item) => item.name === decoded.model) ? model : "";
    }
    const channel = channels.find((item) => item.models.some((entry) => entry.name === model)) || channels[0];
    return channel && channel.models.some((item) => item.name === model) ? encodeChannelModel(channel.id, model) : model;
}

export function resolveModelChannel(config: AiConfig, value: string) {
    const decoded = decodeChannelModel(value);
    const model = decoded?.model || value;
    const matched = decoded ? config.channels.find((channel) => channel.id === decoded.channelId) : config.channels.find((channel) => channel.models.some((item) => item.name === model));
    const channel = matched || config.channels[0] || createModelChannel({ id: "default", name: "默认渠道", baseUrl: config.baseUrl, apiKey: config.apiKey, apiFormat: config.apiFormat, models: config.models.map(modelOptionName).map((name) => ({ name, capability: guessCapability(name) })) });
    return resolveSharedFastBananaKey(config, channel);
}

/** The direct fast channel can reuse a key already configured for the same pdhlzy endpoint without duplicating it in browser storage. */
function resolveSharedFastBananaKey(config: AiConfig, channel: ModelChannel): ModelChannel {
    if (channel.id !== LEGACY_FAST_BANANA_CHANNEL_ID || channel.apiKey.trim() || !isPdhlzyUrl(channel.baseUrl)) return channel;
    const shared = config.channels.find((candidate) => candidate.id !== channel.id && candidate.apiKey.trim() && sameApiBaseUrl(candidate.baseUrl, channel.baseUrl));
    return shared ? { ...channel, apiKey: shared.apiKey } : channel;
}

function sameApiBaseUrl(left: string, right: string) {
    return left.trim().replace(/\/+$/, "").toLowerCase() === right.trim().replace(/\/+$/, "").toLowerCase();
}

export function resolveModelRequestConfig(config: AiConfig, value: string) {
    const channel = resolveModelChannel(config, value);
    return {
        ...config,
        model: modelOptionName(value || config.model),
        baseUrl: channel.baseUrl,
        apiKey: channel.apiKey,
        apiFormat: channel.apiFormat,
    };
}

function normalizeChannels(config: AiConfig) {
    const persistedChannels = Array.isArray(config.channels) ? config.channels : [];
    const channels = persistedChannels
        .filter((channel) => !isLegacyGrsaiBrowserChannel(channel))
        .filter((channel) => !(channel.id === "default" && !channel.apiKey.trim() && (channel.baseUrl === OPENAI_BASE_URL || channel.baseUrl === defaultConfig.baseUrl)))
        .map((channel, index) => {
            const migrated = migratePdhlzyGeminiImageChannel(migrateLegacyFastBananaChannel(channel));
            return createModelChannel({
                ...migrated,
                id: migrated.id || (index === 0 ? "default" : `channel-${index + 1}`),
                name: migrated.name || (index === 0 ? "默认渠道" : `渠道 ${index + 1}`),
                models: normalizeChannelModels(migrated.models),
            });
        });
    if (!channels.length) {
        channels.push(
            createModelChannel({
                id: "default",
                name: "默认渠道",
                baseUrl: config.baseUrl || defaultConfig.baseUrl,
                apiKey: config.apiKey || "",
                apiFormat: config.apiFormat || defaultConfig.apiFormat,
                models: normalizeChannelModels([config.model, config.imageModel, config.videoModel, config.textModel, config.audioModel].map(modelOptionName)),
            }),
        );
    }
    const systemChannel = localWorkbenchChannel();
    const systemChannelIndex = channels.findIndex((channel) => channel.id === LOCAL_WORKBENCH_CHANNEL_ID);
    if (systemChannelIndex >= 0) {
        channels[systemChannelIndex] = systemChannel;
    } else {
        channels.push(systemChannel);
    }
    if (!channels.some((channel) => channel.id === LEGACY_FAST_BANANA_CHANNEL_ID)) channels.push(directBananaChannel());
    return channels;
}

/** Apply the same migrations to imported configs and persisted browser configs. */
export function normalizeAiConfig(persistedConfig: Partial<AiConfig>): AiConfig {
    const config = { ...defaultConfig, ...persistedConfig };
    if (!Array.isArray(persistedConfig.channels)) config.channels = [];
    const channels = normalizeChannels(config);
    const models = modelOptionsFromChannels(channels);
    return {
        ...config,
        channelMode: "local",
        apiFormat: normalizeApiFormat(config.apiFormat),
        channels,
        models,
        imageModel: normalizeModelOptionValue(config.imageModel || config.model, channels),
        videoModel: normalizeModelOptionValue(config.videoModel, channels),
        textModel: normalizeModelOptionValue(config.textModel || config.model, channels),
        audioModel: normalizeModelOptionValue(config.audioModel || defaultConfig.audioModel, channels),
        audioVoice: config.audioVoice || defaultConfig.audioVoice,
        audioFormat: config.audioFormat || defaultConfig.audioFormat,
        audioSpeed: config.audioSpeed || defaultConfig.audioSpeed,
        audioInstructions: config.audioInstructions || "",
        reasoningEffort: config.reasoningEffort || "auto",
        videoSeconds: config.videoSeconds || "6",
        vquality: config.vquality || "720",
        videoGenerateAudio: config.videoGenerateAudio || "true",
        videoWatermark: config.videoWatermark || "false",
        canvasImageCount: config.canvasImageCount || "3",
    };
}

function migrateLegacyFastBananaChannel(channel: ModelChannel): ModelChannel {
    const baseUrl = channel.baseUrl.trim().replace(/\/+$/, "");
    const wasFixedLocalProxy = channel.id === LEGACY_FAST_BANANA_CHANNEL_ID && channel.apiKey === "local-workbench" && /\/fast$/i.test(baseUrl);
    if (wasFixedLocalProxy) return directBananaChannel();
    if (channel.id !== LEGACY_FAST_BANANA_CHANNEL_ID || !isPdhlzyUrl(baseUrl)) return channel;
    const scriptByModel = new Map(DIRECT_BANANA_MODELS.map((model) => [model.name, model.script]));
    return {
        ...channel,
        models: normalizeChannelModels(channel.models).map((model) => ({ ...model, script: model.script || scriptByModel.get(model.name) })),
    };
}

/**
 * pdhlzy exposes Gemini image models through its OpenAI-compatible chat endpoint,
 * not Google's native v1beta generateContent endpoint.  Old imported configs often
 * selected "Gemini" only because the model name begins with gemini; migrate those
 * image-only entries to the working direct-call script without touching the key.
 */
function migratePdhlzyGeminiImageChannel(channel: ModelChannel): ModelChannel {
    const models = normalizeChannelModels(channel.models);
    const hasGeminiImageModel = models.some((model) => model.capability === "image" && /gemini.*image/i.test(model.name));
    if (channel.apiFormat !== "gemini" || !isPdhlzyUrl(channel.baseUrl) || !hasGeminiImageModel) return channel;
    return {
        ...channel,
        apiFormat: "openai",
        models: models.map((model) => (model.capability === "image" && /gemini.*image/i.test(model.name) && !model.script ? { ...model, script: DIRECT_BANANA_SCRIPT } : model)),
    };
}

function isPdhlzyUrl(baseUrl: string) {
    try {
        return new URL(baseUrl).hostname.toLowerCase() === "pdhlzy.com";
    } catch {
        return false;
    }
}

function isLegacyGrsaiBrowserChannel(channel: ModelChannel) {
    if (channel.id === LOCAL_WORKBENCH_CHANNEL_ID || channel.id === LEGACY_FAST_BANANA_CHANNEL_ID) return false;
    try {
        return new URL(channel.baseUrl).hostname.toLowerCase() === "grsai.dakka.com.cn";
    } catch {
        return channel.baseUrl.toLowerCase().includes("grsai.dakka.com.cn");
    }
}

export function defaultBaseUrlForApiFormat(apiFormat: ApiCallFormat) {
    if (apiFormat === "gemini") return GEMINI_BASE_URL;
    if (apiFormat === "ark") return ARK_BASE_URL;
    return OPENAI_BASE_URL;
}

function normalizeApiFormat(apiFormat: unknown): ApiCallFormat {
    return apiFormat === "gemini" || apiFormat === "ark" ? apiFormat : "openai";
}

function uniqueModelOptions(models: string[]) {
    return Array.from(new Set((models || []).map((model) => model.trim()).filter(Boolean)));
}

export function buildApiUrl(baseUrl: string, path: string) {
    let normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
    normalizedBaseUrl = normalizeArkPlanBaseUrl(normalizedBaseUrl);
    const lowerBaseUrl = normalizedBaseUrl.toLowerCase();
    const apiBaseUrl = lowerBaseUrl.endsWith("/v1") || lowerBaseUrl.endsWith("/api/v3") || lowerBaseUrl.endsWith("/api/plan/v3") ? normalizedBaseUrl : `${normalizedBaseUrl}/v1`;
    return `${apiBaseUrl}${path}`;
}

function normalizeArkPlanBaseUrl(baseUrl: string) {
    try {
        const url = new URL(baseUrl);
        const path = url.pathname.replace(/\/+$/, "");
        const lowerPath = path.toLowerCase();
        const arkPlanIndex = lowerPath.indexOf("/api/plan/v3");
        if (arkPlanIndex < 0) return baseUrl;
        const end = arkPlanIndex + "/api/plan/v3".length;
        if (lowerPath.length !== end && lowerPath[end] !== "/") return baseUrl;
        url.pathname = path.slice(0, end);
        url.search = "";
        url.hash = "";
        return url.toString().replace(/\/+$/, "");
    } catch {
        return baseUrl;
    }
}
