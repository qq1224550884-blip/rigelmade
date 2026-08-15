import { Bot, LogOut, Menu, Settings2, Wallet } from "lucide-react";
import { Button, Tooltip } from "antd";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { navigationTools, type NavigationToolSlug } from "@/constant/navigation-tools";
import { MobileNavDrawer } from "@/components/layout/mobile-nav-drawer";
import { UserStatusActions } from "@/components/layout/user-status-actions";
import { cn } from "@/lib/utils";
import { useEffect, useRef, useState } from "react";
import { useAgentStore } from "@/stores/use-agent-store";
import { clearCommercialSession, fetchCommercialConfig, readCommercialSession } from "@/services/commercial-auth";

export function AppTopNav() {
    const { pathname } = useLocation();
    const navigate = useNavigate();
    const [mobileNavOpen, setMobileNavOpen] = useState(false);
    const [paymentEnabled, setPaymentEnabled] = useState(false);
    const autoConnectRef = useRef(false);
    const session = readCommercialSession();
    useEffect(() => { fetchCommercialConfig().then(c => setPaymentEnabled(c.paymentEnabled)); }, []);
    const agentToken = useAgentStore((state) => state.token);
    const agentEnabled = useAgentStore((state) => state.enabled);
    const agentConnected = useAgentStore((state) => state.connected);
    const connectAgent = useAgentStore((state) => state.connectAgent);
    const togglePanel = useAgentStore((state) => state.togglePanel);
    const panelOpen = useAgentStore((state) => state.panelOpen);
    const hideHeader = /^\/canvas\/[^/]+/.test(pathname);
    const slug = pathname.split("/").filter(Boolean)[0];
    const activeToolSlug = navigationTools.some((tool) => tool.slug === slug) ? (slug as NavigationToolSlug) : undefined;

    useEffect(() => {
        if (autoConnectRef.current || agentEnabled || agentConnected || !agentToken.trim()) return;
        autoConnectRef.current = true;
        connectAgent({ silent: true });
    }, [agentConnected, agentEnabled, agentToken, connectAgent]);

    const openTool = (toolSlug: string) => {
        if (!readCommercialSession()) {
            navigate("/login", { state: { from: `/${toolSlug}` } });
            return;
        }
        navigate(`/${toolSlug}`);
    };

    return (
        <>
            {!hideHeader ? (
                <header className="sticky top-0 z-20 h-14 shrink-0 border-b border-stone-200 bg-background/90 backdrop-blur-xl dark:border-stone-800">
                    <div className="mx-auto flex h-full max-w-7xl items-stretch justify-between gap-5 px-6">
                        <div className="flex min-w-0 items-center">
                            <Link to="/" className="flex h-full shrink-0 items-center gap-2 text-sm font-semibold leading-none tracking-tight text-stone-950 transition hover:text-stone-600 dark:text-stone-100 dark:hover:text-stone-300">
                                <span
                                    className="size-5 shrink-0 bg-current"
                                    style={{
                                        mask: "url(/logo.svg) center / contain no-repeat",
                                        WebkitMask: "url(/logo.svg) center / contain no-repeat",
                                    }}
                                />
                                <span className="text-base font-medium">AI 效果图</span>
                                <span className="hidden border-l border-stone-300 pl-2 text-xs font-normal text-stone-500 lg:inline dark:border-stone-700 dark:text-stone-400">商业版</span>
                            </Link>

                            <button
                                type="button"
                                className="ml-3 inline-flex size-8 shrink-0 items-center justify-center text-stone-600 transition hover:text-stone-950 md:hidden dark:text-stone-300 dark:hover:text-white"
                                onClick={() => setMobileNavOpen(true)}
                                aria-label="打开导航菜单"
                                title="导航菜单"
                            >
                                <Menu className="size-5" />
                            </button>

                            <nav className="hide-scrollbar ml-8 hidden h-14 min-w-0 items-center gap-7 overflow-x-auto md:flex">
                                {navigationTools.map((tool) => {
                                    const Icon = tool.icon;
                                    const active = tool.slug === activeToolSlug;
                                    const isPublic = tool.slug === "prompts";
                                    return isPublic ? (
                                        <Link
                                            key={tool.slug}
                                            to={`/${tool.slug}`}
                                            className={cn(
                                                "relative flex h-14 shrink-0 items-center gap-2 text-sm leading-6 transition after:absolute after:inset-x-0 after:bottom-0 after:h-px",
                                                active
                                                    ? "font-medium text-stone-950 after:bg-stone-950 dark:text-stone-100 dark:after:bg-stone-100"
                                                    : "text-stone-500 after:bg-transparent hover:text-stone-950 dark:text-stone-400 dark:hover:text-stone-100",
                                            )}
                                        >
                                            <Icon className="size-4" />
                                            <span className="truncate">{tool.label}</span>
                                        </Link>
                                    ) : (
                                        <button
                                            key={tool.slug}
                                            type="button"
                                            onClick={() => openTool(tool.slug)}
                                            className={cn(
                                                "relative flex h-14 shrink-0 cursor-pointer items-center gap-2 text-sm leading-6 transition after:absolute after:inset-x-0 after:bottom-0 after:h-px",
                                                active
                                                    ? "font-medium text-stone-950 after:bg-stone-950 dark:text-stone-100 dark:after:bg-stone-100"
                                                    : "text-stone-500 after:bg-transparent hover:text-stone-950 dark:text-stone-400 dark:hover:text-stone-100",
                                            )}
                                        >
                                            <Icon className="size-4" />
                                            <span className="truncate">{tool.label}</span>
                                        </button>
                                    );
                                })}
                            </nav>
                        </div>

                        <div className="my-auto flex h-9 min-w-0 items-center justify-end gap-2 justify-self-end whitespace-nowrap">
                            {session ? (<>
                                    {paymentEnabled ? (
                                        <Link to="/billing" className="inline-flex items-center gap-1 text-sm text-stone-600 hover:text-stone-950 dark:text-stone-300 dark:hover:text-white"><Wallet className="size-4" />{session.user.credits ?? 0}</Link>
                                    ) : (
                                        <span className="inline-flex items-center gap-1 text-sm text-stone-500 dark:text-stone-400"><Wallet className="size-4" />{session.user.credits ?? 0}</span>
                                    )}
                                    {session.user.role === "admin" ? <Link to="/admin" className="inline-flex size-8 items-center justify-center text-stone-600 hover:text-stone-950 dark:text-stone-300 dark:hover:text-white" title="运营后台"><Settings2 className="size-4" /></Link> : null}
                                    <Tooltip title={panelOpen ? "收起 Agent" : "打开 Agent"}>
                                        <Button type="text" shape="circle" className="!h-8 !w-8 !min-w-8" icon={<Bot className="size-4" />} onClick={togglePanel} aria-label="打开 Agent" />
                                    </Tooltip>
                                    <UserStatusActions />
                                    <button type="button" className="inline-flex size-8 items-center justify-center text-stone-600 hover:text-stone-950 dark:text-stone-300 dark:hover:text-white" title="退出登录" onClick={() => { clearCommercialSession(); window.location.assign("/"); }}><LogOut className="size-4" /></button>
                                </>) : (
                                <Button type="primary" onClick={() => navigate("/login", { state: { from: pathname } })}>登录 / 注册</Button>
                            )}
                        </div>
                    </div>
                </header>
            ) : null}

            <MobileNavDrawer open={mobileNavOpen} activeToolSlug={activeToolSlug} onClose={() => setMobileNavOpen(false)} onOpenTool={openTool} />
        </>
    );
}
