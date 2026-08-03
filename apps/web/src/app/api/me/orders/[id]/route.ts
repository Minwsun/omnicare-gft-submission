import { NextResponse } from "next/server";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await requireCustomer(); const { id } = await params;
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const order = await prisma.order.findFirst({ where: { id, customerId: user.customerId! }, include: { items: { include: { product: true } }, payments: true, shipments: { include: { events: true } }, refunds: true } });
  if (!order) return NextResponse.json({ error: "ORDER_NOT_ACCESSIBLE" }, { status: 404 });
  return NextResponse.json({ order });
}
