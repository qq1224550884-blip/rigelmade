import { App, Button, Card, Empty, QRCode, Spin, Tag } from "antd";
import { useEffect, useState } from "react";

import { commercialRequest, fetchCommercialConfig } from "@/services/commercial-auth";

type Product = { id: string; name: string; credits: number; amountFen: number };
type LedgerItem = { id: string; delta: number; reason: string; note: string; createdAt: number };

export default function BillingPage() {
    const { message } = App.useApp();
    const [paymentEnabled, setPaymentEnabled] = useState(true);
    const [products, setProducts] = useState<Product[]>([]);
    const [balance, setBalance] = useState(0);
    const [items, setItems] = useState<LedgerItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [payment, setPayment] = useState<{ codeUrl: string; amountFen: number; credits: number; orderId: string } | null>(null);
    const [payStatus, setPayStatus] = useState<"idle" | "waiting" | "paid">("idle");

    const load = async () => {
        setLoading(true);
        try {
            const config = await fetchCommercialConfig();
            setPaymentEnabled(config.paymentEnabled);
            const [catalog, ledger] = await Promise.all([
                commercialRequest<{ products: Product[] }>("/api/catalog/products"),
                commercialRequest<{ balance: number; items: LedgerItem[] }>("/api/billing/ledger"),
            ]);
            setProducts(catalog.products);
            setBalance(ledger.balance);
            setItems(ledger.items);
        } catch (error) {
            message.error(error instanceof Error ? error.message : "无法读取积分账户");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { void load(); }, []);

    const pay = async (productId: string) => {
        try {
            const result = await commercialRequest<{ codeUrl: string; amountFen: number; credits: number; orderId: string }>("/api/payments/wechat/native", { method: "POST", body: JSON.stringify({ productId }) });
            setPayment(result);
            setPayStatus("waiting");
            const orderId = result.orderId;
            const poll = async () => {
                for (let i = 0; i < 60; i++) {
                    await new Promise((r) => setTimeout(r, 3000));
                    try {
                        const st = await commercialRequest<{ paid: boolean; status: string }>("/api/payments/wechat/status", { headers: { "X-Order-Id": orderId } });
                        if (st.paid) {
                            setPayStatus("paid");
                            message.success(`??????? ${result.credits} ??`);
                            void load();
                            return;
                        }
                    } catch { /* keep polling */ }
                }
                setPayStatus("idle");
                message.info("??????????????????");
            };
            void poll();
        } catch (error) {
            message.error(error instanceof Error ? error.message : "??????????");
        }
    };

    if (loading) return <div className="flex h-full items-center justify-center"><Spin /></div>;
    return (
        <main className="h-full overflow-y-auto bg-background px-6 py-10">
            <div className="mx-auto max-w-6xl space-y-10">
                <section className="flex flex-wrap items-end justify-between gap-4 border-b border-stone-200 pb-7 dark:border-stone-800">
                    <div><p className="text-sm text-stone-500">账户积分</p><div className="mt-2 text-5xl font-semibold tracking-tight">{balance}</div></div>
                    <Button onClick={() => void load()}>刷新余额</Button>
                </section>
                <section>
                    <h1 className="text-xl font-semibold">购买积分</h1>
                    {!paymentEnabled ? <Empty className="mt-7" description="支付功能暂未开放，当前为免费体验模式。如需更多积分请联系管理员。" /> :
                    products.length ? <div className="mt-4 grid gap-4 md:grid-cols-3">{products.map((product) => (
                        <Card key={product.id} className="border-stone-200 dark:border-stone-800">
                            <div className="text-base font-semibold">{product.name}</div><div className="mt-5 text-3xl font-semibold">{product.credits} <span className="text-sm font-normal text-stone-500">积分</span></div>
                            <div className="mt-2 text-sm text-stone-500">¥{(product.amountFen / 100).toFixed(2)}</div>
                            <Button type="primary" className="mt-6" block onClick={() => void pay(product.id)}>微信支付</Button>
                        </Card>
                    ))}</div> : <Empty className="mt-7" description="积分套餐尚未上架" />}
                </section>
{payment ? <section className="flex flex-col items-center border-y border-stone-200 py-8 text-center dark:border-stone-800">
                    <div className="font-semibold">{payStatus === "paid" ? "????" : payStatus === "waiting" ? "????????..." : "?????????????"}</div>
                    {payStatus !== "paid" ? <QRCode className="mt-5" value={payment.codeUrl} size={210} /> : null}
                    <p className="mt-4 text-sm text-stone-500">{payStatus === "paid" ? `??? ${payment.credits} ??` : `?? ?${(payment.amountFen / 100).toFixed(2)}??? ${payment.credits} ??`}</p>
                    {payStatus === "paid" ? <Button className="mt-4" onClick={() => { setPayment(null); setPayStatus("idle"); }}>??</Button> : null}
                </section> : null}
                <section><h2 className="text-xl font-semibold">积分明细</h2><div className="mt-4 divide-y divide-stone-200 rounded-lg border border-stone-200 dark:divide-stone-800 dark:border-stone-800">{items.length ? items.map((item) => <div key={item.id} className="flex items-center justify-between gap-4 px-4 py-3"><div><div className="text-sm">{item.note || item.reason}</div><div className="mt-1 text-xs text-stone-500">{new Date(item.createdAt * 1000).toLocaleString("zh-CN")}</div></div><Tag color={item.delta > 0 ? "green" : "red"}>{item.delta > 0 ? "+" : ""}{item.delta}</Tag></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无积分记录" />}</div></section>
            </div>
        </main>
    );
}
