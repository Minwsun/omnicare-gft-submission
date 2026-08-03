import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { z } from "zod";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const node = z.object({ id: z.string(), kind: z.enum(["DOCUMENT","FAQ","POLICY","TERMS","RULE","INTENT","ACTION","PRODUCT_SCOPE","ORDER_STATUS","PAYMENT_STATUS","INCIDENT","ESCALATION"]), name: z.string().trim().min(1).max(180), summary: z.string().max(1000).default(""), content: z.string().max(100000).default(""), importance: z.enum(["LOW","MEDIUM","HIGH","CRITICAL"]), visibility: z.enum(["PUBLIC","CUSTOMER_AUTHENTICATED","INTERNAL"]), marketplace: z.enum(["SHOPEE","TIKTOK_SHOP","INTERNAL"]), mandatory: z.boolean(), archived: z.boolean().default(false), positionX: z.number(), positionY: z.number(), metadata: z.record(z.string(), z.unknown()).default({}) });
const edge = z.object({ id: z.string(), sourceId: z.string(), targetId: z.string(), relation: z.enum(["ANSWERS","GOVERNED_BY","REQUIRES","ALLOWS","PROHIBITS","APPLIES_TO","ESCALATES_TO","AFFECTED_BY","SUPERSEDES","RELATED_TO"]), weight: z.number().min(0).max(1).default(1) });
const schema = z.object({ name: z.string().trim().min(1).max(120).optional(), nodes: z.array(node), edges: z.array(edge) });

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin(); if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const workspace = await prisma.graphWorkspace.findUnique({ where: { id }, include: { draftNodes: { where: { archived: false }, orderBy: { createdAt: "asc" } }, draftEdges: true, issues: { where: { resolved: false } } } });
  return workspace ? NextResponse.json({ workspace }) : NextResponse.json({ error: "WORKSPACE_NOT_FOUND" }, { status: 404 });
}

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin(); if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json()); if (!parsed.success) return NextResponse.json({ error: "INVALID_WORKSPACE", details: parsed.error.flatten() }, { status: 400 });
  const { id } = await params;
  const existing = await prisma.graphWorkspace.findFirst({ where: { id, status: "DRAFT" } }); if (!existing) return NextResponse.json({ error: "DRAFT_WORKSPACE_NOT_FOUND" }, { status: 404 });
  await prisma.$transaction(async (tx) => {
    await tx.graphDraftEdge.deleteMany({ where: { workspaceId: id } });
    await tx.graphDraftNode.deleteMany({ where: { workspaceId: id } });
    if (parsed.data.nodes.length) await tx.graphDraftNode.createMany({ data: parsed.data.nodes.map((item) => ({ ...item, workspaceId: id, metadata: item.metadata as Prisma.InputJsonValue })) });
    if (parsed.data.edges.length) await tx.graphDraftEdge.createMany({ data: parsed.data.edges.map((item) => ({ ...item, workspaceId: id })) });
    await tx.graphWorkspace.update({ where: { id }, data: { name: parsed.data.name, nodes: parsed.data.nodes as Prisma.InputJsonValue, edges: parsed.data.edges as Prisma.InputJsonValue, validation: Prisma.DbNull } });
  });
  return NextResponse.json({ workspace: await prisma.graphWorkspace.findUnique({ where: { id }, include: { draftNodes: true, draftEdges: true } }) });
}
