import { App } from "antd";
import copy from "copy-to-clipboard";

/** Fallback copy using a hidden textarea + execCommand (works on http too). */
function legacyCopy(text: string): boolean {
    try {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.top = "0";
        textarea.style.left = "0";
        textarea.style.opacity = "0";
        textarea.style.pointerEvents = "none";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        const ok = document.execCommand("copy");
        document.body.removeChild(textarea);
        return ok;
    } catch {
        return false;
    }
}

/** Robust copy that works across https/http and desktop/mobile. */
async function copyTextRobust(value: string): Promise<boolean> {
    if (typeof value !== "string" || !value) return false;
    // 1) Modern async clipboard API (needs https or localhost).
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        try {
            await navigator.clipboard.writeText(value);
            return true;
        } catch {
            /* fall through to legacy */
        }
    }
    // 2) copy-to-clipboard lib (uses execCommand internally, may work on http).
    try {
        const ok = await copy(value);
        if (ok) return true;
    } catch {
        /* fall through */
    }
    // 3) Manual textarea + execCommand.
    return legacyCopy(value);
}

export function useCopyText() {
    const { message } = App.useApp();

    return async (text: string, successText = "已复制") => {
        const ok = await copyTextRobust(text);
        if (ok) {
            message.success(successText);
        } else {
            message.error("复制失败，请长按手动复制");
        }
    };
}
