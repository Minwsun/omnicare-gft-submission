import { NextResponse } from "next/server";
import { z } from "zod";

import { requireAdmin } from "@/lib/auth";

const schema = z.object({ query: z.string().trim().min(1).max(2000), profile: z.string().trim().max(100).optional(), limit: z.number().int().min(1).max(20).default(10) });

export async function POST(request: Request) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_QUERY", details: parsed.error.flatten() }, { status: 400 });
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (!serviceUrl) return NextResponse.json({ error: "AI_SERVICE_NOT_CONFIGURED" }, { status: 503 });
  const response = await fetch(`${serviceUrl}/retrieval/search`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...parsed.data, locale: "vi-VN", visibility: "CUSTOMER_AUTHENTICATED" }), cache: "no-store" });
  const results = await response.json();
  return NextResponse.json({ query: parsed.data.query, profile: parsed.data.profile ?? null, rankingPolicy: "hybrid=text+graph+lexical+type+authority", results }, { status: response.status });
}
