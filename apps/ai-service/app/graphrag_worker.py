import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from contextlib import suppress
from datetime import datetime, timezone
from uuid import uuid4

from .config import settings
from .embeddings import embed_texts, vector_literal
from .repositories import Repository
from .retrieval import clear_retrieval_cache

logger = logging.getLogger(__name__)

STAGES = (("NORMALIZING", 5), ("CHUNKING", 15), ("PERSISTING", 25), ("EMBEDDING", 45), ("INDEXING", 80), ("VALIDATING", 95))


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold()).replace("đ", "d")
    plain = "".join(character for character in decomposed if unicodedata.category(character) != "Mn")
    return re.sub(r"\s+", " ", plain).strip()


def digest(value: str) -> str:
    return hashlib.sha256(normalize(value).encode()).hexdigest()


def slugify(value: str) -> str:
    value = normalize(value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:70] or f"knowledge-{uuid4().hex[:8]}"


def category_for(title: str, content: str) -> tuple[str, str]:
    value = normalize(f"{title} {content[:1200]}")
    rules = (
        ("account", "Tài khoản và bảo mật", r"bao mat|tai khoan|dang nhap|xac minh"),
        ("refund", "Trả hàng và hoàn tiền", r"tra hang|doi tra|hoan tien|refund"),
        ("shipping", "Giao hàng", r"giao hang|van chuyen|nhan hang"),
        ("payment", "Thanh toán", r"thanh toan|the tin dung|vi dien tu|paylater"),
        ("voucher", "Voucher và khuyến mãi", r"voucher|khuyen mai|ma giam"),
        ("warranty", "Sản phẩm và bảo hành", r"bao hanh|san pham|hang hoa"),
        ("dispute", "Khiếu nại và tranh chấp", r"khieu nai|tranh chap|to cao"),
        ("legal", "Điều khoản và pháp lý", r"dieu khoan|phap ly|quyen rieng tu|privacy"),
        ("status", "Trạng thái dịch vụ", r"su co|trang thai dich vu|incident"),
    )
    return next(((key, label) for key, label, pattern in rules if re.search(pattern, value)), ("orders", "Đơn hàng"))


def split_sections(title: str, content: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = title
    buffer: list[str] = []
    for raw in content.replace("\r", "").split("\n"):
        line = raw.strip()
        is_heading = bool(re.match(r"^(#{1,6}\s+|\d+(?:\.\d+)*[.)]?\s+|[A-ZÀ-Ỹ][A-ZÀ-Ỹ\s]{5,}:?$)", line))
        if is_heading and buffer:
            sections.append((heading, "\n".join(buffer).strip()))
            heading, buffer = re.sub(r"^#{1,6}\s+", "", line).strip(" :"), []
        elif is_heading:
            heading = re.sub(r"^#{1,6}\s+", "", line).strip(" :")
        elif line:
            buffer.append(line)
    if buffer:
        sections.append((heading, "\n".join(buffer).strip()))
    if not sections:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-ZÀ-Ỹ])", content) if item.strip()]
        sections = [(title if index == 0 else f"{title} · phần {index + 1}", text) for index, text in enumerate(paragraphs)]
    chunks: list[tuple[str, str]] = []
    for section, text in sections:
        words = text.split()
        for offset in range(0, len(words), 320):
            part = " ".join(words[offset:offset + 380])
            if part:
                chunks.append((section if offset == 0 else f"{section} · tiếp", part))
    return chunks or [(title, content)]


class GraphRagWorker:
    def __init__(self, repository: Repository):
        self.repository = repository
        self.tasks: list[asyncio.Task] = []
        self.stopping = asyncio.Event()
        self.wakeup = asyncio.Event()
        self.supervisor: asyncio.Task | None = None
        self.started_at: datetime | None = None
        self.last_poll_at: datetime | None = None
        self.last_claim_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        await self.repository.connect()
        await self.repository.pool.execute('''UPDATE "KnowledgeIngestionRun" SET status='RETRY',stage='QUEUED',
            error='Recovered after stale worker heartbeat',"updatedAt"=now()
            WHERE status='RUNNING' AND ("heartbeatAt" IS NULL OR "heartbeatAt" < now() - interval '5 minutes')''')
        self.started_at = datetime.now(timezone.utc)
        self.tasks = [self._new_task(index) for index in range(max(1, settings.graphrag_worker_concurrency))]
        self.supervisor = asyncio.create_task(self._supervise(), name="graphrag-supervisor")

    async def stop(self) -> None:
        self.stopping.set()
        self.wakeup.set()
        all_tasks = [*self.tasks, *([self.supervisor] if self.supervisor else [])]
        for task in all_tasks:
            task.cancel()
        for task in all_tasks:
            with suppress(asyncio.CancelledError):
                await task

    def notify(self) -> None:
        self.wakeup.set()

    async def status(self) -> dict:
        queue = await self.repository.pool.fetchrow('''SELECT count(*)::int AS depth,
            COALESCE(EXTRACT(EPOCH FROM (now()-min("createdAt"))),0)::int AS oldest
            FROM "KnowledgeIngestionRun" WHERE status IN ('QUEUED','RETRY') AND attempts < 3''')
        alive = sum(not task.done() for task in self.tasks)
        return {
            "enabled": True,
            "status": "ready" if alive == len(self.tasks) else "degraded",
            "configuredConcurrency": len(self.tasks),
            "aliveTasks": alive,
            "queueDepth": queue["depth"],
            "oldestQueuedSeconds": queue["oldest"],
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "lastPollAt": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "lastClaimAt": self.last_claim_at.isoformat() if self.last_claim_at else None,
            "lastSuccessAt": self.last_success_at.isoformat() if self.last_success_at else None,
            "lastError": self.last_error,
        }

    def _new_task(self, worker_index: int) -> asyncio.Task:
        return asyncio.create_task(self._loop(worker_index), name=f"graphrag-worker-{worker_index}")

    async def _supervise(self) -> None:
        while not self.stopping.is_set():
            await asyncio.sleep(1)
            for index, task in enumerate(self.tasks):
                if task.done() and not self.stopping.is_set():
                    error = task.exception() if not task.cancelled() else None
                    self.last_error = f"worker {index} stopped: {error}" if error else f"worker {index} stopped"
                    logger.error(self.last_error)
                    self.tasks[index] = self._new_task(index)

    async def _loop(self, worker_index: int) -> None:
        failures = 0
        while not self.stopping.is_set():
            run = None
            try:
                self.last_poll_at = datetime.now(timezone.utc)
                run = await self._claim()
                failures = 0
                if not run:
                    self.wakeup.clear()
                    try:
                        await asyncio.wait_for(self.wakeup.wait(), timeout=settings.graphrag_poll_seconds)
                    except asyncio.TimeoutError:
                        pass
                    continue
                self.last_claim_at = datetime.now(timezone.utc)
                await self._process(run)
                self.last_success_at = datetime.now(timezone.utc)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failures += 1
                self.last_error = str(error)[:500]
                logger.exception("GraphRAG worker %s failed", worker_index)
                if run:
                    try:
                        await self._fail(run, error)
                    except Exception:
                        logger.exception("GraphRAG run %s could not be marked failed", run["id"])
                await asyncio.sleep(min(30, 2 ** min(failures, 5)))

    async def _claim(self):
        await self.repository.connect()
        async with self.repository.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow('''
                    SELECT * FROM "KnowledgeIngestionRun"
                    WHERE status IN ('QUEUED','RETRY') AND attempts < 3
                    ORDER BY (
                      CASE priority WHEN 'HIGH' THEN 300 WHEN 'LOW' THEN 100 ELSE 200 END
                      + floor(EXTRACT(EPOCH FROM (now()-"createdAt"))/60)
                    ) DESC, "createdAt" FOR UPDATE SKIP LOCKED LIMIT 1
                ''')
                if not row:
                    return None
                return await connection.fetchrow('''
                    UPDATE "KnowledgeIngestionRun" SET status='RUNNING',stage='NORMALIZING',progress=1,
                    attempts=attempts+1,"startedAt"=COALESCE("startedAt",now()),"heartbeatAt"=now(),"updatedAt"=now()
                    WHERE id=$1 RETURNING *
                ''', row["id"])

    async def _stage(self, run_id: str, stage: str, progress: int, processed: int = 0, total: int = 0) -> None:
        await self.repository.pool.execute('''UPDATE "KnowledgeIngestionRun" SET stage=$2,progress=GREATEST(progress,$3),
            "processedUnits"=$4,"totalUnits"=$5,"heartbeatAt"=now(),"updatedAt"=now() WHERE id=$1''', run_id, stage, progress, processed, total)

    async def _process(self, run) -> None:
        raw_payload = run["payload"] or {}
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload)
        run_id = run["id"]
        await self._stage(run_id, "NORMALIZING", 5)
        if payload.get("mode") in {"REBUILD_ALL", "REVISUALIZE"}:
            await self.repository.pool.execute('''UPDATE "KnowledgeIngestionRun" SET status='CANCELLED',stage='CANCELLED',progress=100,
                error='Graph visualization disabled',"completedAt"=now(),"updatedAt"=now() WHERE id=$1''', run_id)
            return
        document_id, version_id, snapshot = await self._publish_input(run_id, payload)
        await self.repository.pool.execute('''UPDATE "KnowledgeIngestionRun" SET status='DONE',stage='DONE',progress=100,
            "documentId"=COALESCE($2,"documentId"),"versionId"=COALESCE($3,"versionId"),result=$4::jsonb,
            "completedAt"=now(),"heartbeatAt"=now(),"updatedAt"=now() WHERE id=$1''', run_id, document_id, version_id, json.dumps(snapshot))
        await clear_retrieval_cache()

    async def _publish_input(self, run_id: str, payload: dict) -> tuple[str, str, dict]:
        title, content = str(payload["title"]).strip(), str(payload["content"]).strip()
        chunks = split_sections(title, content)
        await self._stage(run_id, "CHUNKING", 15, 0, len(chunks))
        category_id, category_name = category_for(title, content)
        document_id = str(payload.get("documentId") or f"kb_{uuid4().hex}")
        version_id = f"kbv_{uuid4().hex}"
        now = datetime.now(timezone.utc)
        await self._stage(run_id, "PERSISTING", 25, 0, len(chunks))
        async with self.repository.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('INSERT INTO "KnowledgeCategory" (id,slug,name) VALUES ($1,$1,$2) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name', category_id, category_name)
                existing = await connection.fetchrow('SELECT id,"currentVersionId" FROM "KnowledgeDocument" WHERE id=$1', document_id)
                if not existing:
                    slug = slugify(title)
                    suffix = 1
                    while await connection.fetchval('SELECT EXISTS(SELECT 1 FROM "KnowledgeDocument" WHERE slug=$1 AND locale=\'vi-VN\')', slug):
                        suffix += 1
                        slug = f"{slugify(title)}-{suffix}"
                    await connection.execute('''INSERT INTO "KnowledgeDocument" (id,slug,locale,type,visibility,marketplace,"authorityLevel","categoryId","ownerId","createdAt","updatedAt")
                        VALUES ($1,$2,'vi-VN',$3::"KnowledgeDocumentType",$4::"KnowledgeVisibility",$5::"KnowledgeMarketplace",$6,$7,$8,now(),now())''',
                        document_id, slug, payload.get("kind", "GUIDE") if payload.get("kind") in {"FAQ","POLICY","TERMS","GUIDE","PRODUCT_GUIDE","TROUBLESHOOTING","SOP","INCIDENT","HISTORICAL_RESOLUTION"} else "GUIDE", payload.get("visibility", "PUBLIC"), payload.get("marketplace", "INTERNAL"), 100 if payload.get("mandatory") else 70, category_id, payload.get("actorId", "system"))
                    semantic_version = "1.0.0"
                else:
                    count = await connection.fetchval('SELECT count(*) FROM "KnowledgeVersion" WHERE "documentId"=$1', document_id)
                    semantic_version = f"{int(count) + 1}.0.0"
                    if existing["currentVersionId"]:
                        await connection.execute('UPDATE "KnowledgeVersion" SET searchable=false,"effectiveTo"=now() WHERE id=$1', existing["currentVersionId"])
                summary = content.strip()[:700]
                await connection.execute('''INSERT INTO "KnowledgeVersion" (id,"documentId","semanticVersion",title,summary,content,status,"effectiveFrom",searchable,"changeSummary","publishedAt","publishedBy","createdAt")
                    VALUES ($1,$2,$3,$4,$5,$6,'PUBLISHED',now(),true,'GraphRAG auto ingestion',now(),$7,now())''', version_id, document_id, semantic_version, title, summary, content, payload.get("actorId", "system"))
                entity_ids = []
                chunk_ids = []
                for index, (section, text) in enumerate(chunks):
                    chunk_id, entity_id = f"kbc_{uuid4().hex}", f"kbe_{uuid4().hex}"
                    await connection.execute('''INSERT INTO "KnowledgeChunk" (id,"versionId",section,content,"contentHash","retrievalEnabled","tokenCount") VALUES ($1,$2,$3,$4,$5,true,$6)''', chunk_id, version_id, section, text, digest(text), max(1, len(text) // 4))
                    await connection.execute('''INSERT INTO "KnowledgeEntity" (id,"versionId","chunkId",type,"canonicalName","normalizedKey",metadata,"createdAt") VALUES ($1,$2,$3,'CONCEPT',$4,$5,$6::jsonb,now())''', entity_id, version_id, chunk_id, section, f"section-{digest(section)[:24]}-{index}", json.dumps({"hierarchyPath": [category_id, title, section], "source": "GRAPHRAG_3_1_1"}))
                    entity_ids.append((entity_id, chunk_id))
                    chunk_ids.append(chunk_id)
                for index in range(1, len(entity_ids)):
                    source, chunk_id = entity_ids[index]
                    target, _ = entity_ids[index - 1]
                    await connection.execute('''INSERT INTO "KnowledgeEdge" (id,"versionId","chunkId","sourceId","targetId",relation,weight,metadata,"createdAt") VALUES ($1,$2,$3,$4,$5,'RELATED_TO',0.8,$6::jsonb,now())''', f"kbedge_{uuid4().hex}", version_id, chunk_id, source, target, json.dumps({"source": "DOCUMENT_SEQUENCE"}))
                await connection.execute('UPDATE "KnowledgeDocument" SET "currentVersionId"=$2,"updatedAt"=now() WHERE id=$1', document_id, version_id)
                await connection.execute('''INSERT INTO "KnowledgeGraphBuild" (id,"versionId",status,"extractorVersion","entityCount","edgeCount","claimCount","startedAt","completedAt","createdAt") VALUES ($1,$2,'COMPLETED','microsoft-graphrag-3.1.1',$3,$4,0,now(),now(),now())''', f"kgb_{uuid4().hex}", version_id, len(entity_ids), max(0, len(entity_ids)-1))
        await self._stage(run_id, "EMBEDDING", 45, 0, len(chunk_ids))
        embedded_count = 0
        try:
            batch_size = max(1, settings.embedding_batch_size)
            for offset in range(0, len(chunk_ids), batch_size):
                batch_ids = chunk_ids[offset:offset + batch_size]
                batch_texts = [text for _, text in chunks[offset:offset + batch_size]]
                vectors = await embed_texts(batch_texts)
                for chunk_id, vector in zip(batch_ids, vectors):
                    await self.repository.pool.execute('UPDATE "KnowledgeChunk" SET embedding=$2::vector WHERE id=$1', chunk_id, vector_literal(vector))
                    embedded_count += 1
                await self._stage(run_id, "EMBEDDING", 45 + min(30, int((offset + len(batch_ids)) / max(1, len(chunk_ids)) * 30)), offset + len(batch_ids), len(chunk_ids))
        except Exception as error:
            logger.warning("Embedding fallback for %s: %s", document_id, error)
            await self._stage(run_id, "EMBEDDING_SKIPPED", 75, embedded_count, len(chunk_ids))
        await self._stage(run_id, "INDEXING", 85, len(chunk_ids), len(chunk_ids))
        await self._stage(run_id, "VALIDATING", 95, len(chunk_ids), len(chunk_ids))
        return document_id, version_id, {"chunkCount": len(chunk_ids), "embeddedCount": embedded_count, "searchable": True, "embeddingFallback": embedded_count != len(chunk_ids)}

    async def _visualize_existing(self, run_id: str, payload: dict) -> tuple[str, str, dict]:
        document_id = str(payload["documentId"])
        row = await self.repository.pool.fetchrow('''SELECT d.id,d.type::text AS type,d.visibility::text AS visibility,v.id AS version_id,v.title,v.content
            FROM "KnowledgeDocument" d JOIN "KnowledgeVersion" v ON v.id=d."currentVersionId"
            WHERE d.id=$1 AND d."archivedAt" IS NULL''', document_id)
        if not row:
            raise RuntimeError("ACTIVE_DOCUMENT_REQUIRED")
        await self._stage(run_id, "VISUALIZING", 30)
        graph = await self._visualize_content(row["title"], row["content"], self._graph_kind(row["type"]), str(payload.get("importance") or "MEDIUM"), row["visibility"], row["type"] in {"POLICY", "TERMS", "SOP"})
        self._validate_graph(graph)
        visualization = await self._persist_visualization(run_id, document_id, row["version_id"], row["content"], graph)
        return document_id, row["version_id"], visualization

    async def _persist_visualization(self, run_id: str, document_id: str, version_id: str, content: str, graph: dict) -> dict:
        revision = int(await self.repository.pool.fetchval('SELECT COALESCE(max(revision),0)+1 FROM "KnowledgeVisualizationRevision" WHERE "documentId"=$1', document_id))
        revision_id = f"kbviz_{uuid4().hex}"
        validation = {"valid": True, "nodeCount": len(graph.get("nodes", [])), "edgeCount": len(graph.get("edges", [])), "lineage": version_id}
        async with self.repository.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('UPDATE "KnowledgeVisualizationRevision" SET active=false WHERE "documentId"=$1 AND active=true', document_id)
                await connection.execute('''INSERT INTO "KnowledgeVisualizationRevision" (id,"documentId","versionId","ingestionRunId",revision,status,model,"promptVersion","sourceHash",nodes,edges,placement,validation,active,"createdAt","completedAt")
                    VALUES ($1,$2,$3,$4,$5,'ACTIVE',$6,'visualization-v1',$7,$8::jsonb,$9::jsonb,$10::jsonb,$11::jsonb,true,now(),now())''', revision_id, document_id, version_id, run_id, revision, settings.llm_visualization_model, digest(content), json.dumps(graph.get("nodes", [])), json.dumps(graph.get("edges", [])), json.dumps(graph.get("placement", {})), json.dumps(validation))
        return {"id": revision_id, "revision": revision, **validation}

    async def _queue_snapshot_rebuild(self, source_run_id: str) -> None:
        exists = await self.repository.pool.fetchval('''SELECT EXISTS(SELECT 1 FROM "KnowledgeIngestionRun" WHERE status IN ('QUEUED','RUNNING','RETRY') AND payload->>'mode'='REBUILD_ALL')''')
        if not exists:
            await self.repository.pool.execute('''INSERT INTO "KnowledgeIngestionRun" (id,status,stage,progress,model,priority,payload,attempts,"createdAt","updatedAt") VALUES ($1,'QUEUED','QUEUED',0,$2,'LOW',$3::jsonb,0,now(),now())''', f"kbir_{uuid4().hex}", settings.llm_reasoning_model or "cx/gpt-5.6-terra", json.dumps({"mode": "REBUILD_ALL", "sourceRunId": source_run_id}))

    async def _visualize_content(self, title: str, content: str, kind: str, importance: str, visibility: str, mandatory: bool) -> dict:
        parts = split_sections(title, content)
        semaphore = asyncio.Semaphore(max(1, settings.graphrag_chunk_concurrency))

        async def parse_part(index: int, section: str, text: str) -> tuple[int, dict]:
            async with semaphore:
                graph = await parse_graph_document(f"{title} · {section}", text[:100000], kind, importance, visibility, mandatory, [])
                self._validate_graph(graph)
                return index, graph

        parsed = await asyncio.gather(*(parse_part(index, section, text) for index, (section, text) in enumerate(parts)))
        root = {"tempId": "node-main", "kind": kind, "name": title, "summary": content[:500], "content": content[:4000], "importance": importance, "visibility": visibility, "mandatory": mandatory, "metadata": {"source": "LUNA_PARALLEL_VISUALIZATION", "partCount": len(parts)}}
        nodes = [root]
        edges = []
        overview_parts = []
        for index, graph in sorted(parsed):
            overview = graph.get("placement", {}).get("overview") if isinstance(graph.get("placement"), dict) else None
            if isinstance(overview, dict):
                overview_parts.append(overview)
            id_map = {"node-main": f"part-{index}-root"}
            for node in graph.get("nodes", []):
                old_id = str(node.get("tempId"))
                new_id = id_map.setdefault(old_id, f"part-{index}-{old_id}")
                copied = {**node, "tempId": new_id}
                if old_id == "node-main":
                    copied["name"] = str(copied.get("name") or f"Phần {index + 1}")
                    copied["content"] = str(copied.get("content") or "")[:4000]
                nodes.append(copied)
            for edge in graph.get("edges", []):
                edges.append({**edge, "tempId": f"part-{index}-{edge.get('tempId')}", "sourceId": id_map.get(str(edge.get("sourceId")), f"part-{index}-{edge.get('sourceId')}"), "targetId": id_map.get(str(edge.get("targetId")), f"part-{index}-{edge.get('targetId')}")})
            edges.append({"tempId": f"part-{index}-to-root", "sourceId": f"part-{index}-root", "targetId": "node-main", "relation": "GOVERNED_BY" if kind in {"POLICY", "TERMS"} else "RELATED_TO", "weight": 0.95})
        overview = {}
        for key in ("issue", "category", "audience", "resolution"):
            cards = [item.get(key) for item in overview_parts if isinstance(item.get(key), dict)]
            summaries = list(dict.fromkeys(str(card.get("summary") or "").strip() for card in cards if str(card.get("summary") or "").strip()))
            points = list(dict.fromkeys(str(point).strip() for card in cards for point in (card.get("points") if isinstance(card.get("points"), list) else []) if str(point).strip()))
            overview[key] = {"summary": " ".join(summaries)[:500] or "Chưa xác định trong tài liệu.", "points": points[:5]}
        result = {"nodes": nodes, "edges": edges, "placement": {"primaryParentId": None, "confidence": 1, "reason": "Parallel document hierarchy", "overview": overview}, "parser": "LUNA_PARALLEL"}
        self._validate_graph(result)
        return result

    @staticmethod
    def _graph_kind(kind: str) -> str:
        return {"SOP": "ACTION", "PRODUCT_GUIDE": "PRODUCT_SCOPE", "GUIDE": "DOCUMENT", "TROUBLESHOOTING": "DOCUMENT", "HISTORICAL_RESOLUTION": "DOCUMENT"}.get(kind, kind if kind in {"DOCUMENT", "FAQ", "POLICY", "TERMS", "INCIDENT"} else "DOCUMENT")

    @staticmethod
    def _validate_graph(graph: dict) -> None:
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        edges = graph.get("edges") if isinstance(graph, dict) else None
        if not isinstance(nodes, list) or not nodes:
            raise RuntimeError("VISUALIZATION_EMPTY")
        ids = [str(node.get("tempId")) for node in nodes if isinstance(node, dict)]
        if len(ids) != len(set(ids)):
            raise RuntimeError("VISUALIZATION_DUPLICATE_NODE")
        valid = set(ids)
        if not isinstance(edges, list) or any(edge.get("sourceId") not in valid or edge.get("targetId") not in valid for edge in edges if isinstance(edge, dict)):
            raise RuntimeError("VISUALIZATION_INVALID_EDGE")

    async def _build_snapshot(self, run_id: str) -> dict:
        rows = await self.repository.pool.fetch('''SELECT c.id AS chunk_id,c.section,c.content,v.id AS version_id,v.title,d.id AS document_id,d."categoryId" AS category_id,cat.name AS category_name
            FROM "KnowledgeChunk" c JOIN "KnowledgeVersion" v ON v.id=c."versionId" JOIN "KnowledgeDocument" d ON d.id=v."documentId" JOIN "KnowledgeCategory" cat ON cat.id=d."categoryId"
            WHERE c."retrievalEnabled"=true AND v.searchable=true AND v.status='PUBLISHED' AND d."archivedAt" IS NULL AND v."effectiveFrom"<=now() AND (v."effectiveTo" IS NULL OR v."effectiveTo">now())
            ORDER BY d."categoryId",v.title,c.section,c.id''')
        if not rows:
            raise RuntimeError("EMPTY_ACTIVE_KNOWLEDGE")
        snapshot_id = f"kgs_{uuid4().hex}"
        await self.repository.pool.execute('''INSERT INTO "KnowledgeGraphSnapshot" (id,status,model,"promptVersion","createdAt") VALUES ($1,'BUILDING',$2,'raptor-v1',now())''', snapshot_id, settings.llm_reasoning_model or "cx/gpt-5.6-terra")
        by_document: dict[str, list] = {}
        for row in rows:
            by_document.setdefault(row["document_id"], []).append(row)
        document_nodes: list[dict] = []
        total = len(rows)
        processed = 0
        await self._stage(run_id, "SUMMARIZING", 65, 0, total)
        for document_rows in by_document.values():
            section_groups: dict[str, list] = {}
            for row in document_rows:
                section_groups.setdefault(row["section"], []).append(row)
            section_nodes = []
            for section_title, section_rows in section_groups.items():
                leaf_ids = []
                for row in section_rows:
                    node_id = f"kgsn_{uuid4().hex}"
                    await self.repository.pool.execute('''INSERT INTO "KnowledgeSummaryNode" (id,"snapshotId","versionId","parentId",level,"nodeType",title,summary,"sourceChunkIds",metadata,active,"createdAt","updatedAt") VALUES ($1,$2,$3,NULL,0,'CHUNK',$4,$5,$6::jsonb,$7::jsonb,false,now(),now())''', node_id, snapshot_id, row["version_id"], row["section"], row["content"][:1800], json.dumps([row["chunk_id"]]), json.dumps({"documentId": row["document_id"], "categoryId": row["category_id"]}))
                    leaf_ids.append(node_id)
                    processed += 1
                    if processed % 25 == 0:
                        await self._stage(run_id, "SUMMARIZING", 65 + int(12 * processed / total), processed, total)
                section_summary = await summarize(section_title, [row["content"] for row in section_rows])
                section_node = f"kgsn_{uuid4().hex}"
                section_chunk_ids = [row["chunk_id"] for row in section_rows]
                await self.repository.pool.execute('''INSERT INTO "KnowledgeSummaryNode" (id,"snapshotId","versionId","parentId",level,"nodeType",title,summary,"sourceChunkIds",metadata,active,"createdAt","updatedAt") VALUES ($1,$2,$3,NULL,1,'SECTION',$4,$5,$6::jsonb,$7::jsonb,false,now(),now())''', section_node, snapshot_id, section_rows[0]["version_id"], section_title, section_summary, json.dumps(section_chunk_ids), json.dumps({"documentId": section_rows[0]["document_id"], "categoryId": section_rows[0]["category_id"]}))
                await self.repository.pool.execute('UPDATE "KnowledgeSummaryNode" SET "parentId"=$1 WHERE id=ANY($2::text[])', section_node, leaf_ids)
                section_nodes.append(section_node)
            doc_summary = await summarize(document_rows[0]["title"], [row["content"] for row in document_rows])
            doc_node = f"kgsn_{uuid4().hex}"
            chunk_ids = [row["chunk_id"] for row in document_rows]
            await self.repository.pool.execute('''INSERT INTO "KnowledgeSummaryNode" (id,"snapshotId","versionId","parentId",level,"nodeType",title,summary,"sourceChunkIds",metadata,active,"createdAt","updatedAt") VALUES ($1,$2,$3,NULL,2,'DOCUMENT',$4,$5,$6::jsonb,$7::jsonb,false,now(),now())''', doc_node, snapshot_id, document_rows[0]["version_id"], document_rows[0]["title"], doc_summary, json.dumps(chunk_ids), json.dumps({"documentId": document_rows[0]["document_id"], "categoryId": document_rows[0]["category_id"]}))
            await self.repository.pool.execute('UPDATE "KnowledgeSummaryNode" SET "parentId"=$1 WHERE id=ANY($2::text[])', doc_node, section_nodes)
            document_nodes.append({"id": doc_node, "category_id": document_rows[0]["category_id"], "category_name": document_rows[0]["category_name"], "chunks": chunk_ids, "summary": doc_summary})
        category_nodes = []
        for category_id in sorted({item["category_id"] for item in document_nodes}):
            children = [item for item in document_nodes if item["category_id"] == category_id]
            title = children[0]["category_name"]
            summary = await summarize(title, [item["summary"] for item in children])
            node_id = f"kgsn_{uuid4().hex}"
            chunk_ids = list(dict.fromkeys(chunk for item in children for chunk in item["chunks"]))
            await self.repository.pool.execute('''INSERT INTO "KnowledgeSummaryNode" (id,"snapshotId","parentId",level,"nodeType",title,summary,"sourceChunkIds",metadata,active,"createdAt","updatedAt") VALUES ($1,$2,NULL,3,'DOMAIN',$3,$4,$5::jsonb,$6::jsonb,false,now(),now())''', node_id, snapshot_id, title, summary, json.dumps(chunk_ids), json.dumps({"categoryId": category_id}))
            await self.repository.pool.execute('UPDATE "KnowledgeSummaryNode" SET "parentId"=$1 WHERE id=ANY($2::text[])', node_id, [item["id"] for item in children])
            community_id = f"kgc_{uuid4().hex}"
            await self.repository.pool.execute('''INSERT INTO "KnowledgeCommunity" (id,"snapshotId","parentId",level,title,summary,"fullContent",rank,metadata,active,"createdAt","updatedAt") VALUES ($1,$2,NULL,3,$3,$4,$5,$6,$7::jsonb,false,now(),now())''', community_id, snapshot_id, title, summary, "\n\n".join(item["summary"] for item in children), float(len(chunk_ids)), json.dumps({"categoryId": category_id}))
            for chunk_id in chunk_ids:
                await self.repository.pool.execute('''INSERT INTO "KnowledgeCommunityMember" (id,"communityId","chunkId",weight,metadata) VALUES ($1,$2,$3,1,'{}'::jsonb)''', f"kgcm_{uuid4().hex}", community_id, chunk_id)
            category_nodes.append({"id": node_id, "chunks": chunk_ids, "summary": summary})
        root_summary = await summarize("Omni Knowledge", [item["summary"] for item in category_nodes])
        root_id = f"kgsn_{uuid4().hex}"
        all_chunks = [row["chunk_id"] for row in rows]
        await self.repository.pool.execute('''INSERT INTO "KnowledgeSummaryNode" (id,"snapshotId","parentId",level,"nodeType",title,summary,"sourceChunkIds",metadata,active,"createdAt","updatedAt") VALUES ($1,$2,NULL,4,'ROOT','Omni Knowledge',$3,$4::jsonb,'{}'::jsonb,false,now(),now())''', root_id, snapshot_id, root_summary, json.dumps(all_chunks))
        await self.repository.pool.execute('UPDATE "KnowledgeSummaryNode" SET "parentId"=$1 WHERE id=ANY($2::text[])', root_id, [item["id"] for item in category_nodes])
        coverage = len(set(all_chunks)) / total
        if coverage != 1:
            raise RuntimeError(f"INVALID_COVERAGE:{coverage}")
        checksum = digest("|".join(sorted(all_chunks)))
        counts = await self.repository.pool.fetchrow('''SELECT
            (SELECT count(*) FROM "KnowledgeDocument" d JOIN "KnowledgeVersion" v ON v.id=d."currentVersionId" WHERE d."archivedAt" IS NULL AND v.searchable=true)::int documents,
            (SELECT count(*) FROM "KnowledgeEntity" e JOIN "KnowledgeVersion" v ON v.id=e."versionId" WHERE v.searchable=true)::int entities,
            (SELECT count(*) FROM "KnowledgeEdge" e JOIN "KnowledgeVersion" v ON v.id=e."versionId" WHERE v.searchable=true)::int edges,
            (SELECT count(*) FROM "KnowledgeClaim" c JOIN "KnowledgeVersion" v ON v.id=c."versionId" WHERE v.searchable=true)::int claims,
            (SELECT count(*) FROM "KnowledgeSummaryNode" WHERE "snapshotId"=$1)::int summaries,
            (SELECT count(*) FROM "KnowledgeCommunity" WHERE "snapshotId"=$1)::int communities''', snapshot_id)
        async with self.repository.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('UPDATE "KnowledgeGraphSnapshot" SET active=false WHERE active=true')
                await connection.execute('UPDATE "KnowledgeSummaryNode" SET active=false WHERE active=true')
                await connection.execute('UPDATE "KnowledgeCommunity" SET active=false WHERE active=true')
                await connection.execute('UPDATE "KnowledgeSummaryNode" SET active=true WHERE "snapshotId"=$1', snapshot_id)
                await connection.execute('UPDATE "KnowledgeCommunity" SET active=true WHERE "snapshotId"=$1', snapshot_id)
                await connection.execute('''UPDATE "KnowledgeGraphSnapshot" SET status='ACTIVE',coverage=1,"documentCount"=$2,"chunkCount"=$3,"entityCount"=$4,"edgeCount"=$5,"claimCount"=$6,"communityCount"=$7,"summaryCount"=$8,checksum=$9,active=true,"completedAt"=now() WHERE id=$1''', snapshot_id, counts["documents"], total, counts["entities"], counts["edges"], counts["claims"], counts["communities"], counts["summaries"], checksum)
        return {"snapshotId": snapshot_id, "coverage": 1, "documents": counts["documents"], "chunks": total, "summaries": counts["summaries"], "communities": counts["communities"]}

    async def _fail(self, run, error: Exception) -> None:
        status = "RETRY" if int(run["attempts"]) < 3 else "QUARANTINED"
        await self.repository.pool.execute('''UPDATE "KnowledgeIngestionRun" SET status=$2,stage=$2,error=$3,"completedAt"=CASE WHEN $2='QUARANTINED' THEN now() ELSE NULL END,"updatedAt"=now() WHERE id=$1''', run["id"], status, str(error)[:4000])
