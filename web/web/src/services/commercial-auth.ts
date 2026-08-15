export type CommercialUser = {
    id: string;
    email: string;
    displayName: string;
    role: "user" | "admin";
    credits: number;
};

type Session = { token: string; user: CommercialUser; expiresAt: number };

const SESSION_KEY = "ai-render-commercial:session";

export type CommercialConfig = { paymentEnabled: boolean; welcomeCredits: number; environment: string };

let _config: CommercialConfig | null = null;

export async function fetchCommercialConfig(): Promise<CommercialConfig> {
    if (_config) return _config;
    try {
        const resp = await fetch("/api/config");
        _config = (await resp.json()) as CommercialConfig;
    } catch {
        _config = { paymentEnabled: false, welcomeCredits: 0, environment: "unknown" };
    }
    return _config;
}

export function readCommercialSession(): Session | null {
    try {
        const value = JSON.parse(localStorage.getItem(SESSION_KEY) || "null") as Session | null;
        return value && value.token && value.expiresAt > Date.now() / 1000 ? value : null;
    } catch {
        return null;
    }
}

export function saveCommercialSession(session: Session) {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearCommercialSession() {
    localStorage.removeItem(SESSION_KEY);
}

export async function commercialRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
    const session = readCommercialSession();
    const headers = new Headers(init.headers);
    if (session?.token) headers.set("Authorization", `Bearer ${session.token}`);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(path, { ...init, headers });
    const value = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(value.detail || "请求失败");
    return value as T;
}
