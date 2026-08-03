import { createHash } from "node:crypto";

import { verify } from "@node-rs/argon2";
import { NextResponse } from "next/server";
import { z } from "zod";

import { createSession } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const schema = z.object({ email: z.email(), password: z.string().min(1).max(128) });

export async function POST(request: Request) {
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_CREDENTIALS" }, { status: 400 });
  const email = parsed.data.email.toLowerCase();
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "local";
  const ipHash = createHash("sha256").update(ip).digest("hex");
  const since = new Date(Date.now() - 15 * 60 * 1000);
  const failures = await prisma.loginAttempt.count({ where: { email, success: false, createdAt: { gte: since } } });
  if (failures >= 5) return NextResponse.json({ error: "LOGIN_RATE_LIMITED" }, { status: 429 });
  const user = await prisma.userAccount.findUnique({ where: { email } });
  const valid = Boolean(user?.active && await verify(user.passwordHash, parsed.data.password).catch(() => false));
  await prisma.loginAttempt.create({ data: { email, ipHash, success: valid } });
  if (!user || !valid) return NextResponse.json({ error: "INVALID_CREDENTIALS" }, { status: 401 });
  await createSession(user.id);
  await prisma.auditLog.create({ data: { actorId: user.id, actorRole: user.role, action: "LOGIN", entityType: "UserAccount", entityId: user.id } });
  return NextResponse.json({ role: user.role, redirectTo: user.role === "ADMIN" ? "/admin" : "/portal" });
}
