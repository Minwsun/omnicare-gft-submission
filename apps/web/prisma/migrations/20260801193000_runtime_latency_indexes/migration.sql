CREATE INDEX IF NOT EXISTS "Order_customerId_status_placedAt_idx" ON "Order"("customerId", status, "placedAt" DESC);
CREATE INDEX IF NOT EXISTS "Shipment_orderId_observedAt_idx" ON "Shipment"("orderId", "observedAt" DESC);
CREATE INDEX IF NOT EXISTS "Ticket_customerId_status_updatedAt_idx" ON "Ticket"("customerId", status, "updatedAt" DESC);
CREATE INDEX IF NOT EXISTS "AiRun_conversationId_startedAt_idx" ON "AiRun"("conversationId", "startedAt" DESC);
CREATE INDEX IF NOT EXISTS "AiStep_runId_idx" ON "AiStep"("runId");
CREATE INDEX IF NOT EXISTS "AiToolCall_runId_idx" ON "AiToolCall"("runId");
CREATE INDEX IF NOT EXISTS "AiRetrievalResult_runId_idx" ON "AiRetrievalResult"("runId");
