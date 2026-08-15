import { useCallback, useEffect, useMemo, useState } from "react";
import { App } from "antd";
import { APP_VERSION } from "@/constant/env";
import type { ReleaseInfo } from "@/lib/release";

// 商业分支不向上游仓库拉取版本：本地版为唯一版本源。
// 若希望展示更新日志，将 __APP_RELEASES__ 构建注入改为本仓库自己的发布记录。
function readLocalReleases(): ReleaseInfo[] {
    return __APP_RELEASES__ || [];
}

function toVersionParts(version: string) {
    const match = version.trim().match(/^v?(\d+)\.(\d+)\.(\d+)/);
    return match ? match.slice(1).map(Number) : null;
}

function isNewerVersion(latestVersion: string, currentVersion: string) {
    const latest = toVersionParts(latestVersion);
    const current = toVersionParts(currentVersion);
    if (!latest || !current) return false;
    return latest.some((value, index) => value > current[index] && latest.slice(0, index).every((part, prevIndex) => part === current[prevIndex]));
}

export function useVersionCheck() {
    const currentVersion = APP_VERSION;
    const { message } = App.useApp();
    const localReleases = useMemo(readLocalReleases, []);
    const [latestVersion, setLatestVersion] = useState(currentVersion);
    const [releases, setReleases] = useState<ReleaseInfo[]>(localReleases);
    const [checking, setChecking] = useState(false);
    const [open, setOpen] = useState(false);
    const hasNewVersion = isNewerVersion(latestVersion, currentVersion);

    // 商业分支：不做联网版本检查，当前版本即最新版本，更新日志来自构建注入。
    const checkLatestVersion = useCallback(async () => {
        setLatestVersion(currentVersion);
        return true;
    }, [currentVersion]);

    const checkLatestRelease = useCallback(
        async (showMessage = false) => {
            setChecking(true);
            setLatestVersion(currentVersion);
            setReleases(localReleases);
            if (showMessage) message.info("当前已是最新版本");
            setChecking(false);
            return true;
        },
        [currentVersion, localReleases, message],
    );

    useEffect(() => {
        void checkLatestVersion();
    }, [checkLatestVersion]);

    const openReleaseModal = useCallback(() => {
        setOpen(true);
        void checkLatestRelease();
    }, [checkLatestRelease]);

    return {
        open,
        setOpen,
        openReleaseModal,
        latestVersion,
        releases,
        checking,
        hasNewVersion,
        checkLatestRelease,
    };
}
