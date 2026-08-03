import { notFound } from "next/navigation";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export default async function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const user = await requireCustomer();
  const { id } = await params;
  const order = await prisma.order.findFirst({
    where: { id, customerId: user!.customerId! },
    include: {
      items: { include: { product: true } },
      payments: { orderBy: { observedAt: "desc" } },
      shipments: { include: { events: { orderBy: { sequence: "asc" } } }, orderBy: { observedAt: "desc" } },
      refunds: { orderBy: { observedAt: "desc" } },
      commerceActions: { orderBy: { createdAt: "desc" } },
    },
  });
  if (!order) notFound();
  const shipment = order.shipments[0];
  return <section className="shell">
    <p className="eyebrow">ORDER OWNERSHIP VERIFIED</p>
    <h1>{order.id}</h1>
    <div className="fact-grid">
      <div><small>Đơn hàng</small><b>{order.status}</b></div>
      <div><small>Thanh toán</small><b>{order.payments[0]?.status ?? "N/A"}</b></div>
      <div><small>Vận chuyển</small><b>{shipment?.status ?? "N/A"}</b></div>
    </div>
    <section className="data-card"><h3>Sản phẩm</h3>{order.items.map((item) => <p key={item.id}>{item.product.name} × {item.quantity} · {Number(item.unitPrice).toLocaleString("vi-VN")} {order.currency}</p>)}</section>
    {shipment && <section className="data-card"><h3>Hành trình giao hàng</h3>{shipment.events.map((event) => <p key={event.id}><b>{event.status}</b> · {event.location ?? "Không có vị trí"} · {event.occurredAt.toLocaleString("vi-VN")}</p>)}</section>}
    <section className="data-card"><h3>Yêu cầu đã thực hiện</h3>{order.commerceActions.length ? order.commerceActions.map((action) => <p key={action.id}><b>{action.type}</b> · {action.status} · {action.createdAt.toLocaleString("vi-VN")}</p>) : <p>Chưa có hành động hỗ trợ.</p>}</section>
    <p className="context">Mở Chat và dùng các nút hỏi nhanh; agent tự nhận diện đơn {order.id} từ trang hiện tại.</p>
  </section>;
}
