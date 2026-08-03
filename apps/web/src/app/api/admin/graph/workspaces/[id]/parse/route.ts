import { NextResponse } from "next/server";
import { z } from "zod";
import { requireAdmin } from "@/lib/auth";

const schema = z.object({ content: z.string().trim().min(20).max(100000), title: z.string().trim().min(1).max(180), kind: z.enum(["DOCUMENT","FAQ","POLICY","TERMS","RULE","INTENT","ACTION","PRODUCT_SCOPE","ORDER_STATUS","PAYMENT_STATUS","INCIDENT","ESCALATION"]), importance: z.enum(["LOW","MEDIUM","HIGH","CRITICAL"]), visibility: z.enum(["PUBLIC","CUSTOMER_AUTHENTICATED","INTERNAL"]), marketplace: z.enum(["SHOPEE","TIKTOK_SHOP","INTERNAL"]), mandatory: z.boolean() });

export async function POST(request: Request) {
  const admin = await requireAdmin(); if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json()); if (!parsed.success) return NextResponse.json({ error: "INVALID_PARSE_INPUT" }, { status: 400 });
  const serviceUrl = process.env.AI_SERVICE_URL || "http://localhost:8000";
  const response = await fetch(`${serviceUrl}/graph/parse`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(parsed.data), cache: "no-store" });
  return NextResponse.json(await response.json(), { status: response.status });
}
