CREATE TABLE "CommerceAction" (
    "id" TEXT NOT NULL,
    "customerId" TEXT NOT NULL,
    "orderId" TEXT NOT NULL,
    "conversationId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "payload" JSONB NOT NULL,
    "result" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "CommerceAction_pkey" PRIMARY KEY ("id")
);

CREATE INDEX "CommerceAction_customerId_createdAt_idx" ON "CommerceAction"("customerId", "createdAt");
CREATE INDEX "CommerceAction_orderId_type_status_idx" ON "CommerceAction"("orderId", "type", "status");
ALTER TABLE "CommerceAction" ADD CONSTRAINT "CommerceAction_customerId_fkey" FOREIGN KEY ("customerId") REFERENCES "Customer"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "CommerceAction" ADD CONSTRAINT "CommerceAction_orderId_fkey" FOREIGN KEY ("orderId") REFERENCES "Order"("id") ON DELETE CASCADE ON UPDATE CASCADE;
