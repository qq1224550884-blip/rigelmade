export const APP_VERSION = __APP_VERSION__ || "dev";

export const DOCS_URL = import.meta.env.VITE_DOC_URL || "https://docs.canvas.best";

// 官方插件清单地址:默认留空即不拉取官方插件列表;如有自建插件源,用 VITE_PLUGIN_REGISTRY_URL 覆盖
export const PLUGIN_REGISTRY_URL = import.meta.env.VITE_PLUGIN_REGISTRY_URL || "";
