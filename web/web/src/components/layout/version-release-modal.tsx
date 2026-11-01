import type { CSSProperties } from "react";
import { Button, Modal, Tabs, Tag, Timeline, theme } from "antd";
import { Megaphone } from "lucide-react";
import { useVersionCheck } from "@/hooks/use-version-check";
import { APP_VERSION } from "@/constant/env";
import { WORKBENCH_ANNOUNCEMENT as announcement } from "@/constant/workbench-announcement";

function getTagColor(type: string) {
    if (type === "新增") return "green";
    if (type === "修复") return "red";
    if (type === "调整") return "blue";
    if (type === "文档") return "purple";
    return "default";
}

function getReleaseTitle(version: string) {
    return version === "Unreleased" ? "未发布" : version;
}

type VersionReleaseModalProps = {
    className?: string;
    style?: CSSProperties;
    compact?: boolean;
};

export function VersionReleaseModal({ className, style, compact = false }: VersionReleaseModalProps) {
    const { open, setOpen, openReleaseModal, latestVersion, releases, hasNewVersion } = useVersionCheck();
    const { token } = theme.useToken();

    return (
        <>
            <button
                type="button"
                className={className || "inline-flex shrink-0 cursor-pointer items-center gap-1 p-1 text-xs font-medium text-stone-500 transition hover:text-stone-950 dark:text-stone-400 dark:hover:text-white"}
                style={style}
                onClick={openReleaseModal}
                title={`更新公告 · ${APP_VERSION}`}
                aria-label="更新公告"
            >
                <span className="relative inline-flex items-center gap-1">
                    <Megaphone className="size-4" />
                    <span className={compact ? "hidden" : "hidden sm:inline"}>更新公告</span>
                    {hasNewVersion ? <span className="absolute -right-1.5 -top-1 size-1.5 rounded-full bg-green-500" /> : null}
                </span>
            </button>
            <Modal title="工作台更新公告" open={open} width={760} centered destroyOnHidden footer={<Button onClick={() => setOpen(false)}>知道了</Button>} onCancel={() => setOpen(false)} styles={{ body: { maxHeight: "70dvh", overflowY: "auto" } }}>
                <Tabs defaultActiveKey="announcement" items={[
                    { key: "announcement", label: "更新公告", children: <article className="space-y-5 pb-2" aria-label="专业效果图工作台升级公告">
                        <header>
                            <h2 className="m-0 text-xl font-semibold leading-snug">{announcement.title}</h2>
                            <div className="mt-2 text-xs" style={{ color: token.colorTextSecondary }}>2026年11月1日 · 当前版本 {APP_VERSION}</div>
                            <p className="mb-0 mt-4 text-sm leading-7">{announcement.summary}</p>
                        </header>
                        {announcement.sections.map((section) => <section key={section.title}>
                            <h3 className="m-0 text-base font-semibold">{section.title}</h3>
                            <p className="mb-0 mt-1.5 text-sm leading-7" style={{ color: token.colorTextSecondary }}>{section.content}</p>
                        </section>)}
                        <p className="text-sm leading-7">{announcement.note}</p>
                        <p className="text-sm leading-7" style={{ color: token.colorTextSecondary }}>{announcement.usage}</p>
                        <footer className="space-y-1 border-t pt-4 text-right text-sm" style={{ borderColor: token.colorBorderSecondary }}>
                            <div>{announcement.signature}</div>
                            <time dateTime={announcement.publishedAt} className="block text-xs" style={{ color: token.colorTextSecondary }}>{announcement.publishedTime}</time>
                        </footer>
                    </article> },
                    { key: "history", label: "版本记录", children: <div>
                    <p className="mb-5 text-sm" style={{ color: token.colorTextSecondary }}>当前版本 {APP_VERSION}</p>
                    <Timeline
                        items={releases.map((release) => ({
                            content: (
                                <div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-sm font-semibold text-stone-950 dark:text-stone-100">{getReleaseTitle(release.version)}</span>
                                        <span className="text-xs text-stone-500 dark:text-stone-400">{release.date}</span>
                                        <div className="flex min-w-0 items-center gap-1.5">
                                            {release.version === latestVersion ? <Tag color="green">最新</Tag> : null}
                                            {release.version === APP_VERSION ? <Tag>当前</Tag> : null}
                                        </div>
                                    </div>
                                    <div className="mt-2 space-y-1.5">
                                        {release.items.map((item, index) => (
                                            <div key={`${release.version}-${index}`} className="flex items-start gap-2 text-sm leading-6 text-stone-700 dark:text-stone-300">
                                                <Tag color={getTagColor(item.type)} className="m-0 mt-0.5 shrink-0 whitespace-nowrap">
                                                    {item.type}
                                                </Tag>
                                                <span className="min-w-0 flex-1">{item.content}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ),
                        }))}
                    />
                    {!releases.length ? <p className="text-sm" style={{ color: token.colorTextSecondary }}>暂无版本记录，可在「更新公告」查看本次升级内容。</p> : null}
                    </div> },
                ]} />
            </Modal>
        </>
    );
}
