import { NextResponse } from "next/server";
import { z } from "zod";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const schema = z.object({ name: z.string().trim().min(1).max(120) });

export async function GET() {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const workspaces = await prisma.graphWorkspace.findMany({ include: { _count: { select: { draftNodes: true, draftEdges: true, issues: true } } }, orderBy: { updatedAt: "desc" }, take: 30 });
  return NextResponse.json({ workspaces });
}

export async function POST(request: Request) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_WORKSPACE" }, { status: 400 });
  const workspace = await prisma.graphWorkspace.create({ data: { name: parsed.data.name, nodes: [], edges: [], createdBy: admin.id } });
  return NextResponse.json({ workspace }, { status: 201 });
}
