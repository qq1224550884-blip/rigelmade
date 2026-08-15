import { Link } from "react-router-dom";

export default function TermsPage() {
    return (
        <div className="min-h-screen bg-stone-50 dark:bg-stone-950 px-6 py-12 text-stone-800 dark:text-stone-200">
            <div className="mx-auto max-w-2xl prose prose-stone dark:prose-invert">
                <h1 className="text-2xl font-bold mb-6">服务条款 & 隐私说明</h1>

                <h2>1. 服务性质</h2>
                <p>本工具是一个开源的 AI 图像生成工作台，基于 AGPL-3.0 协议开放源代码。我们提供账号注册、积分计费和 AI 图像/视频生成服务，按实际消耗扣除积分。</p>

                <h2>2. 用户内容与责任</h2>
                <ul>
                    <li>您通过本工具生成的所有内容，由您自行承担责任。请勿生成违法、侵权、暴力、色情或侵犯他人权益的内容。</li>
                    <li>本工具不对 AI 生成内容的准确性、版权状态或商业可用性做任何保证。</li>
                    <li>如发现违规内容，我们将配合相关法律法规进行处理，包括但不限于删除内容、封禁账号。</li>
                </ul>

                <h2>3. 积分与支付</h2>
                <ul>
                    <li>积分一经充值不予退款，请根据实际需求选择套餐。</li>
                    <li>生成失败时积分自动退还，不会重复扣费。</li>
                    <li>本工具保留调整定价和套餐的权利，调整前已充值的积分不受影响。</li>
                </ul>

                <h2>4. 隐私保护</h2>
                <ul>
                    <li>我们收集您的邮箱地址仅用于账号注册和登录，不会用于营销或分享给第三方。</li>
                    <li>您的密码经过加密存储，我们无法查看明文密码。</li>
                    <li>生成的图片记录仅您本人可见。</li>
                    <li>我们不使用追踪 Cookie 或第三方分析服务（除非您主动授权）。</li>
                </ul>

                <h2>5. 服务可用性</h2>
                <p>本工具依赖第三方 AI 渠道（API 提供方）。如因渠道故障、维护或政策变更导致服务中断，我们不承担赔偿责任，但会尽力恢复服务。</p>

                <h2>6. 知识产权</h2>
                <p>本工具前端基于 infinite-canvas（AGPL-3.0）二次开发，源代码已公开。您使用本工具生成的内容的版权归属，适用相关法律和 AI 平台的使用条款。建议您在商用前自行评估版权风险。</p>

                <h2>7. 联系我们</h2>
                <p>如有问题或投诉，请通过以下方式联系我们，我们会在 3 个工作日内回复。</p>
                <p className="text-stone-500 dark:text-stone-400 text-sm mt-6">
                    联系方式请见网站首页或相关社交媒体账号。
                </p>

                <div className="mt-8 pt-6 border-t border-stone-200 dark:border-stone-800">
                    <Link to="/login" className="text-blue-600 dark:text-blue-400 hover:underline text-sm">← 返回登录</Link>
                </div>
            </div>
        </div>
    );
}
