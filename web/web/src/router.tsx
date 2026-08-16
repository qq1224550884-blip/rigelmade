import { createBrowserRouter, Navigate, Outlet, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { AnalyticsTracker } from "@/components/layout/analytics-tracker";
import { AppConfigPanel } from "@/components/layout/app-config-modal";
import UserLayout from "@/layouts/user-layout";
import AssetsPage from "@/pages/assets";
import CanvasPage from "@/pages/canvas";
import CanvasProjectPage from "@/pages/canvas/project";
import HomePage from "@/pages/home";
import ImagePage from "@/pages/image";
import NotFound from "@/pages/not-found";
import PromptsPage from "@/pages/prompts";
import VideoPage from "@/pages/video";
import AuthPage from "@/pages/auth";
import TermsPage from "@/pages/terms";
import BillingPage from "@/pages/billing";
import AdminPage from "@/pages/admin";
import { readCommercialSession } from "@/services/commercial-auth";

function RequireCommercialAuth({ children }: { children: ReactNode }) {
    const location = useLocation();
    return readCommercialSession() ? <>{children}</> : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}

export const router = createBrowserRouter([
    {
        element: <UserLayout><AnalyticsTracker /><Outlet /></UserLayout>,
        children: [
            { path: "/", element: <HomePage /> },
            { path: "/prompts", element: <PromptsPage /> },
        ],
    },
    {
        element: (
            <RequireCommercialAuth><UserLayout><AnalyticsTracker /><Outlet /></UserLayout></RequireCommercialAuth>
        ),
        children: [
            { path: "/image", element: <ImagePage /> },
            { path: "/video", element: <VideoPage /> },
            { path: "/assets", element: <AssetsPage /> },
            { path: "/canvas", element: <CanvasPage /> },
            { path: "/canvas/:id", element: <CanvasProjectPage /> },
            { path: "/billing", element: <BillingPage /> },
            { path: "/admin", element: <AdminPage /> },
            { path: "/config", element: <AppConfigPanel showDoneButton /> },
        ],
    },
    { path: "/login", element: <AuthPage /> },
    { path: "/terms", element: <TermsPage /> },
    { path: "*", element: <NotFound /> },
]);
