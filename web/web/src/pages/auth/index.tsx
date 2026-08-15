import { App, Button, Card, Form, Input, Tabs } from "antd";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { commercialRequest, saveCommercialSession, type CommercialUser } from "@/services/commercial-auth";

type AuthResult = { token: string; expiresAt: number; user: CommercialUser };

export default function AuthPage() {
    const { message } = App.useApp();
    const [loading, setLoading] = useState(false);
    const location = useLocation();
    const from = (location.state as { from?: string } | null)?.from || "/";

    const submit = async (mode: "login" | "register", values: { email: string; password: string; displayName?: string }) => {
        setLoading(true);
        try {
            if (mode === "register") {
                const result = await commercialRequest<{ user: unknown; welcomeCredits?: number }>("/api/auth/register", { method: "POST", body: JSON.stringify(values) });
                if (result.welcomeCredits && result.welcomeCredits > 0) {
                    message.success(`注册成功！已赠送 ${result.welcomeCredits} 积分，请登录体验。`);
                } else {
                    message.success("注册成功，请登录。");
                }
                return;
            }
            const result = await commercialRequest<AuthResult>("/api/auth/login", { method: "POST", body: JSON.stringify(values) });
            saveCommercialSession(result);
            window.location.assign(from);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "操作失败");
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="flex min-h-dvh items-center justify-center bg-stone-100 px-5 py-12 dark:bg-stone-950">
            <Card className="w-full max-w-md shadow-sm" styles={{ body: { padding: 30 } }}>
                <div className="mb-7">
                    <div className="text-2xl font-semibold text-stone-950 dark:text-stone-100">RigelMade 工作台</div>
                    <p className="mt-2 text-sm leading-6 text-stone-500">登录后即可使用生图、画布等全部功能，积分由服务器统一结算。</p>
                </div>
                <Tabs
                    items={[
                        {
                            key: "login",
                            label: "登录",
                            children: <AuthForm loading={loading} onSubmit={(values) => void submit("login", values)} />,
                        },
                        {
                            key: "register",
                            label: "注册",
                            children: <AuthForm register loading={loading} onSubmit={(values) => void submit("register", values)} />,
                        },
                    ]}
                />
                <div className="mt-4 flex items-center justify-between text-xs">
                    <Link to="/" className="text-stone-500 hover:text-stone-700 dark:text-stone-400 dark:hover:text-stone-200">← 返回首页</Link>
                    <Link to="/terms" className="underline text-stone-400 hover:text-stone-600 dark:text-stone-500 dark:hover:text-stone-300">服务条款 & 隐私说明</Link>
                </div>
            </Card>
        </main>
    );
}

function AuthForm({ register = false, loading, onSubmit }: { register?: boolean; loading: boolean; onSubmit: (values: { email: string; password: string; displayName?: string }) => void }) {
    return (
        <Form layout="vertical" requiredMark={false} onFinish={onSubmit}>
            {register ? <Form.Item name="displayName" label="昵称" rules={[{ required: true, message: "请输入昵称" }]}><Input autoComplete="nickname" /></Form.Item> : null}
            <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}><Input autoComplete="email" /></Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 10, message: "密码至少 10 位" }]}><Input.Password autoComplete={register ? "new-password" : "current-password"} /></Form.Item>
            <Button htmlType="submit" type="primary" block loading={loading}>{register ? "创建账号" : "登录工作台"}</Button>
        </Form>
    );
}
