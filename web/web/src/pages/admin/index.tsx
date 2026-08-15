import { App, Button, Card, Form, Input, InputNumber, Modal, Space, Switch, Table, Tabs, Tag } from "antd";
import { useEffect, useState } from "react";

import { commercialRequest } from "@/services/commercial-auth";

type Product = { id: string; name: string; credits: number; amountFen: number; active: boolean };
type ModelPrice = { model: string; quality: string; credits: number; active: boolean; updatedAt: number };
type KeyStatus = { name: string; total_keys: number; active_keys: number; keys: { index: number; prefix: string; calls: number; errors: number; cooldown_remaining: number; last_error: string }[] };
type AdminUser = {
    id: string;
    email: string;
    displayName: string;
    role: "user" | "admin";
    status: "active" | "disabled";
    createdAt: number;
    credits: number;
    spentCredits: number;
    generationCount: number;
};

const formatTime = (value: number) => new Date(value * 1000).toLocaleString("zh-CN", { hour12: false });

export default function AdminPage() {
    const { message } = App.useApp();
    const [products, setProducts] = useState<Product[]>([]);
    const [prices, setPrices] = useState<ModelPrice[]>([]);
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [loading, setLoading] = useState(false);
    const [keyPools, setKeyPools] = useState<Record<string, KeyStatus>>({});
    const [creditUser, setCreditUser] = useState<AdminUser | null>(null);
    const [creditForm] = Form.useForm<{ delta: number; note: string }>();

    const load = async () => {
        setLoading(true);
        try {
            const [productData, priceData, userData, keyData] = await Promise.all([
                commercialRequest<{ products: Product[] }>("/api/admin/products"),
                commercialRequest<{ items: ModelPrice[] }>("/api/admin/model-prices"),
                commercialRequest<{ users: AdminUser[] }>("/api/admin/users"),
                commercialRequest<{ pools: Record<string, KeyStatus> }>("/api/admin/keys"),
            ]);
            setProducts(productData.products);
            setPrices(priceData.items);
            setUsers(userData.users);
            setKeyPools(keyData.pools);
        } catch (error) { message.error(error instanceof Error ? error.message : "无管理员权限"); }
        finally { setLoading(false); }
    };

    useEffect(() => { void load(); }, []);

    const addProduct = async (values: { name: string; credits: number; amountFen: number; active: boolean }) => {
        try { await commercialRequest("/api/admin/products", { method: "POST", body: JSON.stringify(values) }); message.success("套餐已保存"); void load(); }
        catch (error) { message.error(error instanceof Error ? error.message : "保存失败"); }
    };

    const setPrice = async (values: { model: string; quality: string; credits: number; active: boolean }) => {
        try { await commercialRequest("/api/admin/model-prices", { method: "PUT", body: JSON.stringify(values) }); message.success("模型积分价格已保存"); void load(); }
        catch (error) { message.error(error instanceof Error ? error.message : "保存失败"); }
    };

    const toggleUser = async (user: AdminUser) => {
        const nextStatus = user.status === "active" ? "disabled" : "active";
        try {
            await commercialRequest(`/api/admin/users/${user.id}/status`, { method: "PATCH", body: JSON.stringify({ status: nextStatus }) });
            message.success(nextStatus === "active" ? "用户已启用" : "用户已停用");
            void load();
        } catch (error) { message.error(error instanceof Error ? error.message : "状态更新失败"); }
    };

    const adjustCredits = async (values: { delta: number; note: string }) => {
        if (!creditUser) return;
        try {
            await commercialRequest(`/api/admin/users/${creditUser.id}/credits`, { method: "POST", body: JSON.stringify(values) });
            message.success("积分已调整");
            setCreditUser(null);
            creditForm.resetFields();
            void load();
        } catch (error) { message.error(error instanceof Error ? error.message : "积分调整失败"); }
    };

    return <main className="h-full overflow-y-auto bg-background px-6 py-10">
        <div className="mx-auto max-w-7xl">
            <h1 className="text-2xl font-semibold">运营后台</h1>
            <p className="mt-2 text-sm text-stone-500">管理注册用户、积分套餐和模型扣费标准。</p>
            <Tabs className="mt-7" items={[
                {
                    key: "users",
                    label: "用户管理",
                    children: <Card>
                        <Table
                            rowKey="id"
                            loading={loading}
                            pagination={{ pageSize: 20 }}
                            scroll={{ x: 980 }}
                            dataSource={users}
                            columns={[
                                { title: "用户", fixed: "left", width: 210, render: (_: unknown, row: AdminUser) => <div><div className="font-medium">{row.displayName}</div><div className="text-xs text-stone-500">{row.email}</div></div> },
                                { title: "角色", width: 90, render: (_: unknown, row: AdminUser) => row.role === "admin" ? <Tag color="blue">管理员</Tag> : <Tag>用户</Tag> },
                                { title: "状态", width: 90, render: (_: unknown, row: AdminUser) => row.status === "active" ? <Tag color="green">正常</Tag> : <Tag color="red">已停用</Tag> },
                                { title: "积分余额", dataIndex: "credits", width: 110 },
                                { title: "累计消费", dataIndex: "spentCredits", width: 110 },
                                { title: "成功生成", dataIndex: "generationCount", width: 100 },
                                { title: "注册时间", width: 170, render: (_: unknown, row: AdminUser) => formatTime(row.createdAt) },
                                {
                                    title: "操作",
                                    fixed: "right",
                                    width: 190,
                                    render: (_: unknown, row: AdminUser) => <Space>
                                        <Button size="small" onClick={() => { setCreditUser(row); creditForm.setFieldsValue({ delta: undefined, note: "管理员调整" }); }}>调积分</Button>
                                        <Button size="small" danger={row.status === "active"} onClick={() => void toggleUser(row)}>{row.status === "active" ? "停用" : "启用"}</Button>
                                    </Space>,
                                },
                            ]}
                        />
                    </Card>,
                },
                {
                    key: "products",
                    label: "积分套餐",
                    children: <div className="grid gap-6 lg:grid-cols-[360px_1fr]"><Card title="新建套餐"><Form layout="vertical" initialValues={{ active: false }} onFinish={(values) => void addProduct(values)}><Form.Item name="name" label="套餐名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="credits" label="积分数量" rules={[{ required: true }]}><InputNumber className="w-full" min={1} precision={0} /></Form.Item><Form.Item name="amountFen" label="价格（分）" rules={[{ required: true }]}><InputNumber className="w-full" min={1} precision={0} /></Form.Item><Form.Item name="active" label="立即上架" valuePropName="checked"><Switch /></Form.Item><Button htmlType="submit" type="primary">保存套餐</Button></Form></Card><Table rowKey="id" loading={loading} pagination={false} dataSource={products} columns={[{ title: "名称", dataIndex: "name" }, { title: "积分", dataIndex: "credits" }, { title: "价格", render: (_: unknown, row: Product) => `¥${(row.amountFen / 100).toFixed(2)}` }, { title: "状态", render: (_: unknown, row: Product) => row.active ? "已上架" : "未上架" }]} /></div>,
                },
                {
                    key: "prices",
                    label: "模型扣费",
                    children: <div className="grid gap-6 lg:grid-cols-[360px_1fr]"><Card title="设置积分价格"><Form layout="vertical" initialValues={{ quality: "low", active: true }} onFinish={(values) => void setPrice(values)}><Form.Item name="model" label="模型" rules={[{ required: true }]}><Input placeholder="例如 gpt-image-2" /></Form.Item><Form.Item name="quality" label="画质" rules={[{ required: true }]}><Input placeholder="例如 low / medium / high" /></Form.Item><Form.Item name="credits" label="单次积分" rules={[{ required: true }]}><InputNumber className="w-full" min={1} precision={0} /></Form.Item><Form.Item name="active" label="允许生成" valuePropName="checked"><Switch /></Form.Item><Button htmlType="submit" type="primary">保存价格</Button></Form></Card><Table rowKey={(row: ModelPrice) => `${row.model}-${row.quality}`} loading={loading} pagination={false} dataSource={prices} columns={[{ title: "模型", dataIndex: "model" }, { title: "画质", dataIndex: "quality" }, { title: "积分", dataIndex: "credits" }, { title: "状态", render: (_: unknown, row: ModelPrice) => row.active ? "启用" : "停用" }]} /></div>,
                },
                {
                    key: "keys",
                    label: "Key 状态",
                    children: <div className="grid gap-6">{Object.entries(keyPools).map(([provider, pool]) => (
                        <Card key={provider} title={`${provider} (${pool.active_keys}/${pool.total_keys} 可用)`}>
                            {pool.total_keys === 0 ? <p className="text-sm text-stone-500">未配置 Key</p> :
                            <Table rowKey="index" pagination={false} dataSource={pool.keys} columns={[
                                { title: "Key", dataIndex: "prefix", width: 180 },
                                { title: "调用次数", dataIndex: "calls", width: 100 },
                                { title: "错误次数", dataIndex: "errors", width: 100 },
                                { title: "状态", render: (_: unknown, row: KeyStatus["keys"][0]) => row.cooldown_remaining > 0 ? <Tag color="orange">冷却中 {row.cooldown_remaining}s</Tag> : <Tag color="green">可用</Tag> },
                                { title: "最后错误", render: (_: unknown, row: KeyStatus["keys"][0]) => row.last_error ? <span className="text-xs text-red-500">{row.last_error}</span> : <span className="text-xs text-stone-400">—</span> },
                            ]} />}
                        </Card>
                    ))}</div>,
                },
            ]} />
        </div>
        <Modal title={creditUser ? `调整 ${creditUser.displayName} 的积分` : "调整积分"} open={Boolean(creditUser)} destroyOnClose footer={null} onCancel={() => { setCreditUser(null); creditForm.resetFields(); }}>
            <Form form={creditForm} layout="vertical" onFinish={(values) => void adjustCredits(values)} initialValues={{ note: "管理员调整" }}>
                <Form.Item name="delta" label="调整数量（可填负数）" rules={[{ required: true, message: "请输入积分数量" }]}><InputNumber className="w-full" precision={0} /></Form.Item>
                <Form.Item name="note" label="备注"><Input maxLength={200} /></Form.Item>
                <Button type="primary" htmlType="submit">确认调整</Button>
            </Form>
        </Modal>
    </main>;
}
