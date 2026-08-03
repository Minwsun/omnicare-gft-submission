import { createHash } from "node:crypto";
import { NextResponse } from "next/server";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const allowed = new Map([["ffd8ff", "image/jpeg"], ["89504e", "image/png"], ["524946", "image/webp"]]);

export async function POST(request: Request) {
  const user = await requireCustomer();
  if (!user?.customerId) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const form = await request.formData();
  const conversationId = String(form.get("conversationId") || "");
  const file = form.get("file");
  if (!(file instanceof File) || !conversationId) return NextResponse.json({ error: "FILE_AND_CONVERSATION_REQUIRED" }, { status: 400 });
  if (file.size < 1 || file.size > 10 * 1024 * 1024) return NextResponse.json({ error: "INVALID_FILE_SIZE" }, { status: 413 });
  const conversation = await prisma.conversation.findFirst({ where: { id: conversationId, customerId: user.customerId, channel: "WEB" }, select: { id: true } });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  const bytes = Buffer.from(await file.arrayBuffer());
  const signature = bytes.subarray(0, 3).toString("hex");
  const mimeType = signature === "ffd8ff" ? allowed.get(signature) : signature === "89504e" ? allowed.get(signature) : bytes.subarray(0, 4).toString("ascii") === "RIFF" && bytes.subarray(8, 12).toString("ascii") === "WEBP" ? "image/webp" : undefined;
  if (!mimeType) return NextResponse.json({ error: "UNSUPPORTED_IMAGE" }, { status: 415 });
  const checksum = createHash("sha256").update(bytes).digest("hex");
  const attachment = await prisma.chatAttachment.upsert({
    where: { conversationId_checksum: { conversationId, checksum } },
    update: { bytes, deletedAt: null, status: "UPLOADED" },
    create: { conversationId, customerId: user.customerId, fileName: file.name.slice(0, 180), mimeType, size: bytes.length, checksum, bytes },
    select: { id: true, fileName: true, mimeType: true, size: true, status: true },
  });
  return NextResponse.json({ attachment: { ...attachment, url: `/api/chat/attachments/${attachment.id}` } }, { status: 201 });
}
