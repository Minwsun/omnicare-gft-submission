import Link from "next/link";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export default async function OrdersPage() {
  const user = await requireCustomer();
  const orders = await prisma.order.findMany({ where: { customerId: user!.customerId! }, include: { shipments: true, payments: true }, orderBy: { placedAt: "desc" } });
  return <section className="shell"><p className="eyebrow">VERIFIED TRANSACTIONS</p><h1>Đơn hàng của tôi</h1><div className="data-list">{orders.map((order) => <Link className="data-card" href={`/portal/orders/${order.id}`} key={order.id}><header><b>{order.id}</b><span>{order.status}</span></header><p>{Number(order.totalAmount).toLocaleString("vi-VN")} {order.currency}</p><small>Thanh toán: {order.payments[0]?.status ?? "N/A"} · Giao hàng: {order.shipments[0]?.status ?? "N/A"}</small></Link>)}</div></section>;
}
