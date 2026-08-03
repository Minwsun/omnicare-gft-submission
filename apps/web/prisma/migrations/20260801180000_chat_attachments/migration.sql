CREATE TABLE "ChatAttachment" (
  "id" TEXT NOT NULL,
  "conversationId" TEXT NOT NULL,
  "messageId" TEXT,
  "customerId" TEXT NOT NULL,
  "fileName" TEXT NOT NULL,
  "mimeType" TEXT NOT NULL,
  "size" INTEGER NOT NULL,
  "checksum" TEXT NOT NULL,
  "bytes" BYTEA,
  "status" TEXT NOT NULL DEFAULT 'UPLOADED',
  "analysis" JSONB,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt" TIMESTAMP(3),
  CONSTRAINT "ChatAttachment_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "ChatAttachment_conversationId_checksum_key" ON "ChatAttachment"("conversationId", "checksum");
CREATE INDEX "ChatAttachment_customerId_conversationId_createdAt_idx" ON "ChatAttachment"("customerId", "conversationId", "createdAt");
CREATE INDEX "ChatAttachment_messageId_idx" ON "ChatAttachment"("messageId");
ALTER TABLE "ChatAttachment" ADD CONSTRAINT "ChatAttachment_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "Conversation"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "ChatAttachment" ADD CONSTRAINT "ChatAttachment_messageId_fkey" FOREIGN KEY ("messageId") REFERENCES "Message"("id") ON DELETE SET NULL ON UPDATE CASCADE;
