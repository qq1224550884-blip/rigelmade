import { Drawer } from "antd";
import { Link } from "react-router-dom";

import { navigationTools, type NavigationToolSlug } from "@/constant/navigation-tools";
import { cn } from "@/lib/utils";

type MobileNavDrawerProps = {
    open: boolean;
    activeToolSlug?: NavigationToolSlug;
    onClose: () => void;
    onOpenTool?: (slug: string) => void;
};

export function MobileNavDrawer({ open, activeToolSlug, onClose, onOpenTool }: MobileNavDrawerProps) {
    return (
        <Drawer title="导航" placement="left" size={280} open={open} onClose={onClose} className="md:hidden">
            <div className="space-y-1">
                {navigationTools.map((tool) => {
                    const Icon = tool.icon;
                    const active = tool.slug === activeToolSlug;
                    const isPublic = tool.slug === "prompts";
                    const className = cn(
                        "flex items-center gap-3 rounded-lg px-3 py-3 text-base transition",
                        active ? "bg-stone-100 font-medium text-stone-950 dark:bg-stone-800 dark:text-stone-100" : "text-stone-600 hover:bg-stone-100 hover:text-stone-950 dark:text-stone-300 dark:hover:bg-stone-800 dark:hover:text-stone-100",
                    );
                    if (isPublic) {
                        return (
                            <Link key={tool.slug} to={`/${tool.slug}`} onClick={onClose} className={className}>
                                <Icon className="size-5" />
                                <span>{tool.label}</span>
                            </Link>
                        );
                    }
                    return (
                        <button key={tool.slug} type="button" onClick={() => { onClose(); onOpenTool?.(tool.slug); }} className={`${className} w-full cursor-pointer`}>
                            <Icon className="size-5" />
                            <span>{tool.label}</span>
                        </button>
                    );
                })}
            </div>
        </Drawer>
    );
}
