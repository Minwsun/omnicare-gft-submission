import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!await requireAdmin()) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const nodes = await prisma.knowledgeSummaryNode.findMany({ where: { parentId: id, active: true }, orderBy: { title: "asc" }, take: 200 });
  return NextResponse.json({ nodes });
}
