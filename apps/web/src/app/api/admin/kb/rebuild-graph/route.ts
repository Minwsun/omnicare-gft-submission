import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";

export async function POST() {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (!serviceUrl) return NextResponse.json({ error: "AI_SERVICE_NOT_CONFIGURED" }, { status: 503 });
  const response = await fetch(`${serviceUrl}/retrieval/rebuild-all`, { method: "POST", cache: "no-store" });
  return NextResponse.json(await response.json(), { status: response.status });
}
