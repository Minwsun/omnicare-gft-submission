import Link from "next/link";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export default async function PortalPage() {
  const user = await requireCustomer();
  const orders = await prisma.order.count({ where: { customerId: user!.customerId! } });
  return <section className="shell"><p className="eyebrow">CUSTOMER PORTAL</p><h1>Xin chào, {user!.customer?.name}</h1><div className="metrics"><Metric value={String(orders)} label="Đơn hàng" /><Metric value="408" label="Tài liệu hỗ trợ" /><Metric value="24/7" label="AI support" /></div><div className="article-grid"><Card href="/portal/chat" title="Hỏi OmniCare AI" text="Tra cứu giao dịch và chính sách có dẫn nguồn." /><Card href="/portal/orders" title="Đơn hàng" text="Theo dõi thanh toán, vận chuyển và hoàn tiền." /><Card href="/help" title="Help Center" text="Đọc FAQ, policy và hướng dẫn hiện hành." /></div></section>;
}
function Metric({ value, label }: { value: string; label: string }) { return <div className="metric"><b>{value}</b><span>{label}</span></div>; }
function Card({ href, title, text }: { href: string; title: string; text: string }) { return <article><h3>{title}</h3><p>{text}</p><Link href={href}>Mở →</Link></article>; }
