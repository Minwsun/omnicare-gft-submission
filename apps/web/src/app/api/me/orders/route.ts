import { NextResponse } from "next/server";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const orders = await prisma.order.findMany({ where: { customerId: user.customerId! }, orderBy: { placedAt: "desc" }, take: 20 });
  return NextResponse.json({ orders });
}
