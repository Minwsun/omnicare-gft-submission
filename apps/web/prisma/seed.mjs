import { PrismaClient } from "@prisma/client";
import { createHash } from "node:crypto";
import { hash } from "@node-rs/argon2";

const prisma = new PrismaClient();
const seedNow = new Date();
const deliveryDate = new Date("2026-07-30T11:00:00.000Z");

function knowledgeHash(value) {
  return createHash("sha256").update(value).digest("hex");
}

function omniBrandText(value) {
  return value
    .replace(/Shopee\s*VIP/gi, "OmniVIP")
    .replace(/SPayLater/gi, "OmniPayLater")
    .replace(/ShopeeFood/gi, "OmniFood")
    .replace(/Shopee\s+Xu/gi, "Omni Xu")
    .replace(/Shopee/gi, "Omni");
}

const categories = [
  ["account", "tai-khoan-bao-mat", "Tài khoản và bảo mật"],
  ["orders", "dat-hang", "Đặt hàng"],
  ["shipping", "giao-hang", "Giao hàng"],
  ["payment", "thanh-toan", "Thanh toán"],
  ["refund", "doi-tra-hoan-tien", "Đổi trả và hoàn tiền"],
  ["voucher", "voucher-khuyen-mai", "Voucher và khuyến mãi"],
  ["warranty", "bao-hanh-san-pham", "Bảo hành và sản phẩm"],
  ["dispute", "khieu-nai-tranh-chap", "Khiếu nại và tranh chấp"],
  ["legal", "dieu-khoan-phap-ly", "Điều khoản và pháp lý"],
  ["status", "thong-bao-dich-vu", "Thông báo dịch vụ"],
];

const categorySubjects = {
  account: ["đổi mật khẩu", "xác minh email", "bảo vệ tài khoản", "đăng nhập", "cập nhật hồ sơ"],
  orders: ["tạo đơn", "kiểm tra đơn", "thay đổi sản phẩm", "xác nhận đơn", "hủy đơn chưa thanh toán"],
  shipping: ["theo dõi giao hàng", "giao trễ", "giao thiếu", "đổi địa chỉ giao", "đơn đã giao chưa nhận"],
  payment: ["thanh toán thất bại", "giao dịch đang xử lý", "xuất hóa đơn", "thanh toán trùng", "phương thức thanh toán"],
  refund: ["điều kiện hoàn tiền", "thời gian hoàn tiền", "trả sản phẩm", "trạng thái hoàn tiền", "phí đổi trả"],
  voucher: ["voucher hết hạn", "điều kiện voucher", "mã không áp dụng", "giới hạn khuyến mãi", "hoàn voucher"],
  warranty: ["thời hạn bảo hành", "đăng ký bảo hành", "sản phẩm lỗi", "trung tâm bảo hành", "bằng chứng mua hàng"],
  dispute: ["mở khiếu nại", "bổ sung bằng chứng", "thời gian xử lý", "tranh chấp giao hàng", "liên hệ nhân viên"],
  legal: ["điều khoản sử dụng", "quyền riêng tư", "xóa dữ liệu", "quyền khách hàng", "lưu trữ thông tin"],
  status: ["sự cố thanh toán", "gián đoạn giao hàng", "bảo trì hệ thống", "dịch vụ chậm", "khôi phục dịch vụ"],
};

function orderStatus(index) {
  return ["PENDING", "CONFIRMED", "PROCESSING", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"][index % 6];
}

function paymentStatus(index) {
  return ["PENDING", "AUTHORIZED", "CAPTURED", "CAPTURED", "CAPTURED", "FAILED"][index % 6];
}

function shipmentStatus(status) {
  return { PENDING: "PENDING", CONFIRMED: "PENDING", PROCESSING: "PENDING", SHIPPED: "IN_TRANSIT", OUT_FOR_DELIVERY: "OUT_FOR_DELIVERY", DELIVERED: "DELIVERED" }[status];
}

async function seedCommerce() {
  for (let index = 1; index <= 2; index += 1) {
    const customerId = `customer_${String(index).padStart(3, "0")}`;
    await prisma.customer.upsert({
      where: { id: customerId }, update: {},
      create: { id: customerId, name: `Khách hàng ${index}`, email: `customer${index}@example.test`, phoneMasked: `******${String(6700 + index)}`, tier: index === 1 ? "GOLD" : "REGULAR" },
    });
    await prisma.address.upsert({
      where: { id: `addr_${index}` }, update: {},
      create: { id: `addr_${index}`, customerId, label: "Nhà", recipient: `Khách hàng ${index}`, line1: `${index} Đường Nguyễn Văn Linh`, city: index % 2 ? "TP. Hồ Chí Minh" : "Hà Nội" },
    });
  }

  for (let index = 1; index <= 12; index += 1) {
    const productCategory = ["MOBILE", "AUDIO", "HOME", "ACCESSORY", "BEAUTY", "FASHION", "MOM_BABY", "GROCERY"][index % 8];
    const productData = { brand: ["Nova", "Aster", "Lumi", "Mori", "VinaHome"][index % 5], description: "Sản phẩm chính hãng, có bảo hành và đổi trả theo chính sách.", price: 79000 + (index % 80) * 125000, stock: index % 19 === 0 ? 0 : 5 + (index * 7) % 96, rating: 3.8 + (index % 12) / 10, soldCount: 20 + index * 13, active: true, metadata: { colors: ["Đen", "Trắng"], warrantyMonths: 12 } };
    await prisma.product.upsert({
      where: { id: `prd_${String(index).padStart(4, "0")}` }, update: productData,
      create: { id: `prd_${String(index).padStart(4, "0")}`, sku: `SKU-${String(index).padStart(5, "0")}`, name: `${["Điện thoại", "Tai nghe", "Máy gia dụng", "Phụ kiện", "Mỹ phẩm", "Thời trang", "Mẹ và bé", "Thực phẩm"][index % 8]} ${index}`, category: productCategory, ...productData },
    });
    await prisma.productReturnProfile.upsert({
      where: { productId: `prd_${String(index).padStart(4, "0")}` },
      update: {},
      create: {
        productId: `prd_${String(index).padStart(4, "0")}`,
        returnable: true,
        sealedRequired: ["BEAUTY", "GROCERY", "MOM_BABY"].includes(["MOBILE", "AUDIO", "HOME", "ACCESSORY", "BEAUTY", "FASHION", "MOM_BABY", "GROCERY"][index % 8]),
        accessoriesRequired: ["MOBILE", "AUDIO", "HOME"].includes(["MOBILE", "AUDIO", "HOME", "ACCESSORY", "BEAUTY", "FASHION", "MOM_BABY", "GROCERY"][index % 8]),
        evidenceTypes: ["PHOTO", "PACKAGE_LABEL"],
        exclusions: ["USED_BEYOND_INSPECTION", "MISSING_SERIAL"],
      },
    });
  }

  for (let index = 1; index <= 8; index += 1) {
    const orderId = `ORD-${1000 + index}`;
    const customerId = `customer_${String(((index - 1) % 2) + 1).padStart(3, "0")}`;
    const productId = `prd_${String(((index - 1) % 12) + 1).padStart(4, "0")}`;
    const status = index === 1 ? "OUT_FOR_DELIVERY" : orderStatus(index);
    const amount = 450000 + index * 85000;
    const placedAt = new Date(seedNow.getTime() - ((index % 90) + 1) * 86400000);
    await prisma.order.upsert({
      where: { id: orderId }, update: {},
      create: {
        id: orderId, customerId, status, totalAmount: amount, placedAt,
        items: { create: { productId, quantity: (index % 3) + 1, unitPrice: amount } },
        payments: { create: { id: `pay_${orderId}`, provider: ["VNPAY", "MOMO", "COD", "BANK_CARD"][index % 4], status: index === 1 ? "CAPTURED" : paymentStatus(index), amount, maskedReference: `PAY-***${1000 + index}`, observedAt: seedNow } },
        shipments: { create: { id: `shp_${orderId}`, carrier: ["SPX Express", "Giao Hàng Nhanh", "Viettel Post"][index % 3], trackingMasked: `SHIP-***${1000 + index}`, status: shipmentStatus(status), estimatedDelivery: new Date(seedNow.getTime() + ((index % 5) + 1) * 86400000), observedAt: seedNow, events: { create: [{ sequence: 1, status: "PICKED_UP", occurredAt: placedAt }, { sequence: 2, status: shipmentStatus(status), occurredAt: seedNow }] } } },
      },
    });
    if (index % 10 === 0) {
      await prisma.refund.upsert({
        where: { id: `ref_${orderId}` }, update: {},
        create: { id: `ref_${orderId}`, orderId, status: ["REQUESTED", "PENDING_APPROVAL", "PROCESSING", "COMPLETED"][index % 4], amount: Math.floor(amount / 2), reason: "Khách hàng yêu cầu hoàn tiền sau khi kiểm tra hàng", observedAt: seedNow, referenceId: `REF-***${1000 + index}` },
      });
    }
  }
}

async function seedReturnRules() {
  const categoryWindows = { MOBILE: 7, AUDIO: 7, HOME: 15, ACCESSORY: 7, BEAUTY: 3, FASHION: 15, MOM_BABY: 3, GROCERY: 2 };
  const reasons = ["DAMAGED", "WRONG_ITEM", "MISSING_ITEM", "NOT_AS_DESCRIBED", "CHANGE_OF_MIND"];
  for (const [category, windowDays] of Object.entries(categoryWindows)) {
    for (const reasonCode of reasons) {
      const sealedRequired = ["BEAUTY", "GROCERY", "MOM_BABY"].includes(category) && reasonCode === "CHANGE_OF_MIND";
      await prisma.returnPolicyRule.upsert({
        where: { id: `return_${category.toLowerCase()}_${reasonCode.toLowerCase()}` }, update: {},
        create: {
          id: `return_${category.toLowerCase()}_${reasonCode.toLowerCase()}`, category, reasonCode, windowDays,
          returnable: !(sealedRequired && ["BEAUTY", "GROCERY"].includes(category)), sealedRequired,
          evidenceTypes: reasonCode === "CHANGE_OF_MIND" ? ["PACKAGE_PHOTO"] : ["PRODUCT_PHOTO", "PACKAGE_LABEL"],
          conditions: { orderStatus: "DELIVERED", itemOwnedByCustomer: true },
          exceptions: { openedSeal: sealedRequired, hygieneSensitive: ["BEAUTY", "GROCERY", "MOM_BABY"].includes(category) },
          effectiveFrom: new Date("2026-01-01T00:00:00.000Z"), documentId: "policy_refund_core", versionId: "policy_refund_core_v_2026_2",
        },
      });
    }
  }
}

async function seedAccounts() {
  const accounts = [
    { email: "admin@test.com", password: "admin", role: "ADMIN", customerId: null },
    { email: "user1@test.com", password: "user", role: "CUSTOMER", customerId: "customer_001" },
    { email: "user2@test.com", password: "user", role: "CUSTOMER", customerId: "customer_002" },
  ];
  await prisma.userAccount.deleteMany({ where: { email: { notIn: accounts.map((account) => account.email) } } });
  for (const account of accounts) {
    const passwordHash = await hash(account.password, { algorithm: 2, memoryCost: 19456, timeCost: 2, parallelism: 1 });
    await prisma.userAccount.upsert({
      where: { email: account.email },
      update: { passwordHash, role: account.role, customerId: account.customerId, active: true },
      create: { email: account.email, passwordHash, role: account.role, customerId: account.customerId },
    });
  }
  await prisma.customer.update({ where: { id: "customer_001" }, data: { name: "Nguyễn Minh Anh", email: "minhanh.customer@omnicare.local" } });
  await prisma.customer.update({ where: { id: "customer_002" }, data: { name: "Trần Lan Anh", email: "lananh.customer@omnicare.local" } });
}

async function upsertKnowledge({ id, type, visibility, categoryId, authority, title, summary, content, version = "1.0.0", effectiveFrom = "2026-01-01", effectiveTo = null }) {
  title = omniBrandText(title);
  summary = omniBrandText(summary);
  content = omniBrandText(content);
  const versionId = `${id}_v_${version.replaceAll(".", "_")}`;
  const chunkId = `${versionId}_chunk_1`;
  await prisma.knowledgeDocument.upsert({
    where: { id }, update: { type, visibility, authorityLevel: authority, categoryId },
    create: { id, slug: id.replaceAll("_", "-"), type, visibility, authorityLevel: authority, categoryId, ownerId: type === "SOP" ? "ops_demo" : "admin_demo" },
  });
  await prisma.knowledgeVersion.upsert({
    where: { id: versionId }, update: { title, summary, content, status: "PUBLISHED", searchable: true },
    create: { id: versionId, documentId: id, semanticVersion: version, title, summary, content, status: "PUBLISHED", effectiveFrom: new Date(`${effectiveFrom}T00:00:00.000Z`), effectiveTo: effectiveTo ? new Date(`${effectiveTo}T00:00:00.000Z`) : null, searchable: true, changeSummary: "Khởi tạo bộ tri thức kiểm thử đã qua validation", publishedAt: seedNow, publishedBy: "system_seed" },
  });
  await prisma.knowledgeChunk.upsert({
    where: { id: chunkId }, update: { section: title, content, contentHash: knowledgeHash(content), tokenCount: content.split(/\s+/).length },
    create: { id: chunkId, versionId, section: title, content, contentHash: knowledgeHash(content), tokenCount: content.split(/\s+/).length },
  });
  await prisma.knowledgeDocument.update({ where: { id }, data: { currentVersionId: versionId } });
  await buildKnowledgeGraph({ id, type, visibility, categoryId, authority, title, content, versionId, chunkId, effectiveFrom, effectiveTo });
}

function normalizeKey(value) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

async function buildKnowledgeGraph({ id, type, visibility, categoryId, authority, title, content, versionId, chunkId, effectiveFrom, effectiveTo }) {
  await prisma.knowledgeEdge.deleteMany({ where: { versionId } });
  await prisma.knowledgeClaim.deleteMany({ where: { versionId } });
  await prisma.knowledgeEntity.deleteMany({ where: { versionId } });
  await prisma.knowledgeGraphBuild.deleteMany({ where: { versionId } });
  const build = await prisma.knowledgeGraphBuild.create({ data: { versionId, status: "RUNNING", extractorVersion: "hybrid-ontology-3.0", startedAt: seedNow } });
  const subjectType = type === "INCIDENT" ? "INCIDENT" : type === "POLICY" || type === "TERMS" ? "POLICY_RULE" : type === "PRODUCT_GUIDE" || type === "TROUBLESHOOTING" ? "PRODUCT" : "CONCEPT";
  const documentEntity = await prisma.knowledgeEntity.create({ data: { versionId, chunkId, type: subjectType, canonicalName: title, normalizedKey: normalizeKey(`${id}-${title}`), metadata: { documentId: id, visibility, documentType: type } } });
  const intentEntity = await prisma.knowledgeEntity.create({ data: { versionId, chunkId, type: "INTENT", canonicalName: categoryId, normalizedKey: normalizeKey(`intent-${categoryId}`), metadata: { categoryId } } });
  const scopeEntity = await prisma.knowledgeEntity.create({ data: { versionId, chunkId, type: "CONCEPT", canonicalName: `${categoryId} scope`, normalizedKey: normalizeKey(`scope-${categoryId}-${id}`), metadata: { categoryId, visibility } } });
  const actionEntity = await prisma.knowledgeEntity.create({ data: { versionId, chunkId, type: "ACTION", canonicalName: type === "SOP" ? "Human handoff" : type === "INCIDENT" ? "Service response" : "Customer support action", normalizedKey: normalizeKey(`action-${type}-${id}`), metadata: { documentId: id, sourceChunkId: chunkId } } });
  const relation = type === "HISTORICAL_RESOLUTION" ? "RELATED_TO" : type === "INCIDENT" ? "AFFECTED_BY" : type === "SOP" ? "ESCALATES_TO" : type === "POLICY" || type === "TERMS" ? "GOVERNED_BY" : "ANSWERS";
  await prisma.knowledgeEdge.create({ data: { versionId, chunkId, sourceId: intentEntity.id, targetId: documentEntity.id, relation, weight: authority / 100, metadata: { visibility, provenance: chunkId } } });
  await prisma.knowledgeEdge.createMany({ data: [
    { versionId, chunkId, sourceId: documentEntity.id, targetId: scopeEntity.id, relation: "APPLIES_TO", weight: authority / 100, metadata: { provenance: chunkId } },
    { versionId, chunkId, sourceId: documentEntity.id, targetId: actionEntity.id, relation: type === "SOP" ? "ESCALATES_TO" : "ALLOWS", weight: authority / 100, metadata: { provenance: chunkId } },
    { versionId, chunkId, sourceId: scopeEntity.id, targetId: actionEntity.id, relation: "REQUIRES", weight: 0.8, metadata: { provenance: chunkId } },
  ] });
  const statements = content.split(/[.!?]+/).map((value) => value.trim()).filter((value) => value.length > 20).slice(0, 3);
  for (const [index, statement] of statements.entries()) {
    await prisma.knowledgeClaim.create({ data: { versionId, chunkId, subject: title, predicate: type === "INCIDENT" ? "service_status" : type === "FAQ" ? "answers" : type === "POLICY" || type === "TERMS" ? "governs" : "supports", value: statement, polarity: statement.toLowerCase().includes("không được") ? -1 : 1, authorityLevel: authority, effectiveFrom: new Date(`${effectiveFrom}T00:00:00.000Z`), effectiveTo: effectiveTo ? new Date(`${effectiveTo}T00:00:00.000Z`) : null, scope: { visibility, documentType: type, statementIndex: index, sourceChunkId: chunkId } } });
  }
  await prisma.knowledgeGraphBuild.update({ where: { id: build.id }, data: { status: "COMPLETED", entityCount: 4, edgeCount: 4, claimCount: statements.length, completedAt: seedNow } });
}

async function seedKnowledge() {
  const categoryIds = new Map();
  for (const [id, slug, name] of categories) {
    const existing = await prisma.knowledgeCategory.findUnique({ where: { slug } });
    if (existing) {
      await prisma.knowledgeCategory.update({ where: { id: existing.id }, data: { name } });
      categoryIds.set(id, existing.id);
    } else {
      await prisma.knowledgeCategory.create({ data: { id, slug, name } });
      categoryIds.set(id, id);
    }
  }

  const criticalPolicies = [
    ["shipping", "Chính sách giao hàng", "Thời gian giao hiển thị là dự kiến và có thể thay đổi theo đơn vị vận chuyển, khu vực, thời tiết hoặc sự cố dịch vụ. Khách hàng theo dõi hành trình trong chi tiết đơn. Địa chỉ chỉ được đổi khi đơn chưa bàn giao cho đơn vị vận chuyển và hệ thống còn cho phép chỉnh sửa. Nếu đơn quá ETA, báo đã giao nhưng chưa nhận, giao nhầm hoặc thất lạc, hệ thống phải xác minh trạng thái bằng công cụ giao vận và chuyển điều tra khi chưa thể kết luận an toàn."],
    ["refund", "Chính sách đổi trả và hoàn tiền", "Khách hàng có thể yêu cầu đổi trả khi nhận sai hàng, thiếu hàng, hàng hỏng, không hoạt động hoặc khác đáng kể so với mô tả. Điều kiện phụ thuộc trạng thái đơn, thời hạn đổi trả, nhóm sản phẩm và bằng chứng ảnh hoặc video. Hệ thống phải kiểm tra đúng đơn và từng sản phẩm trước khi kết luận. Hoàn tiền chỉ được tạo dưới dạng yêu cầu chờ phê duyệt; AI không tự chuyển tiền hoặc cam kết thời điểm tiền về khi chưa có trạng thái giao dịch đã xác minh."],
    ["payment", "Chính sách thanh toán", "Omni hỗ trợ thanh toán khi nhận hàng nếu đơn và khu vực đủ điều kiện, thẻ ngân hàng và các phương thức điện tử được hiển thị tại bước thanh toán. AUTHORIZED chỉ có nghĩa ngân hàng đã giữ hoặc chấp thuận khoản tiền; chỉ CAPTURED mới được thông báo là thanh toán hoàn tất. Khi thanh toán thất bại, khách hàng cần kiểm tra số dư, hạn mức, thông tin thẻ, kết nối và thử lại; giao dịch bị trừ tiền nhưng đơn không ghi nhận phải được tra soát theo mã đơn và mã giao dịch."],
    ["warranty", "Chính sách bảo hành", "Quyền bảo hành phụ thuộc sản phẩm, ngày mua và bằng chứng giao dịch đã xác minh."],
    ["legal", "Chính sách quyền riêng tư", "Omni xử lý thông tin tài khoản, liên hệ, địa chỉ giao hàng, lịch sử đơn, thanh toán, hỗ trợ và dữ liệu kỹ thuật cần thiết để vận hành dịch vụ, chống gian lận và giải quyết tranh chấp. Dữ liệu chỉ được truy cập sau xác minh danh tính, giới hạn theo mục đích hỗ trợ và có thể được chia sẻ cho đơn vị thanh toán, vận chuyển hoặc cơ quan có thẩm quyền trong phạm vi cần thiết. Khách hàng có thể yêu cầu xem, sửa hoặc xử lý dữ liệu theo quy trình xác minh danh tính."],
    ["voucher", "Chính sách voucher và khuyến mãi", "Voucher chỉ áp dụng khi còn hiệu lực và thỏa mãn sản phẩm, giá trị đơn tối thiểu, phương thức thanh toán, khu vực, số lượt và tài khoản áp dụng. Voucher hết hạn thông thường không được khôi phục. Mã báo không hợp lệ cần kiểm tra ký tự, thời hạn, điều kiện giỏ hàng và giới hạn sử dụng. Việc hoàn voucher sau hủy hoặc hoàn tiền phụ thuộc điều kiện của từng chương trình."],
    ["account", "An toàn tài khoản và phòng chống lừa đảo", "Omni không yêu cầu mật khẩu, OTP hoặc chuyển tiền qua đường link lạ, tin nhắn tuyển dụng hay liên hệ ngoài ứng dụng. Không đăng nhập qua link không xác minh, không chuyển khoản ngoài luồng thanh toán chính thức. Khi có đăng nhập lạ, thay đổi email không phải do khách hàng, giao dịch không nhận diện hoặc đã cung cấp OTP, khách hàng phải đổi mật khẩu, đăng xuất thiết bị lạ và liên hệ hỗ trợ khẩn cấp."],
  ];
  for (const [categoryId, title, content] of criticalPolicies) {
    await upsertKnowledge({ id: `policy_${categoryId}_core`, type: "POLICY", visibility: "PUBLIC", categoryId: categoryIds.get(categoryId), authority: 100, title, summary: `Chính sách cốt lõi về ${categories.find(([id]) => id === categoryId)[2].toLowerCase()}.`, content, version: "2026.2" });
  }

  await upsertKnowledge({
    id: "kb_app_support_core",
    type: "TROUBLESHOOTING",
    visibility: "PUBLIC",
    categoryId: categoryIds.get("account"),
    authority: 95,
    title: "Khắc phục lỗi ứng dụng Omni",
    summary: "Các bước an toàn khi ứng dụng lỗi, bị văng, không nhận thông báo hoặc cần cập nhật.",
    content: "Khi ứng dụng Omni gặp lỗi, hãy kiểm tra kết nối mạng, đóng và mở lại ứng dụng, sau đó cập nhật ứng dụng lên phiên bản mới nhất từ kho ứng dụng chính thức. Nếu ứng dụng bị văng hoặc hoạt động chậm, có thể xóa bộ nhớ đệm rồi đăng nhập lại; không cài phần mềm hoặc tệp từ nguồn lạ. Nếu không nhận được thông báo, kiểm tra quyền thông báo của ứng dụng và chế độ tiết kiệm pin trên thiết bị. Nếu lỗi vẫn còn, ghi lại mã lỗi, thời điểm xảy ra và ảnh chụp màn hình để nhân viên hỗ trợ kiểm tra.",
    version: "2026.1",
  });

  for (let index = 1; index <= 0; index += 1) {
    const categoryId = categories[index % categories.length][0];
    await upsertKnowledge({ id: `policy_${String(index).padStart(3, "0")}`, type: "POLICY", visibility: "PUBLIC", categoryId: categoryIds.get(categoryId), authority: 95, title: `Chính sách ${categories[index % categories.length][2]} ${index}`, summary: "Tài liệu chính sách dùng cho môi trường kiểm thử.", content: `Quy định số ${index}: trạng thái giao dịch phải được xác minh bằng công cụ dữ liệu. Không cam kết quyền lợi khi thiếu bằng chứng.`, version: "2026.1" });
  }
  for (let index = 1; index <= 0; index += 1) {
    await upsertKnowledge({ id: `terms_${String(index).padStart(3, "0")}`, type: "TERMS", visibility: "PUBLIC", categoryId: categoryIds.get("legal"), authority: 100, title: `Điều khoản sử dụng ${index}`, summary: "Điều khoản dùng cho môi trường kiểm thử.", content: `Điều khoản số ${index}. Nội dung kiểm thử không thay thế tư vấn pháp lý hoặc điều khoản của doanh nghiệp thật.`, version: "2026.1" });
  }
  for (let index = 1; index <= 0; index += 1) {
    const categoryId = categories[(index - 1) % categories.length][0];
    const subjects = categorySubjects[categoryId];
    const subject = subjects[index % subjects.length];
    await upsertKnowledge({ id: `faq_${String(index).padStart(3, "0")}`, type: "FAQ", visibility: "PUBLIC", categoryId: categoryIds.get(categoryId), authority: 70, title: `Làm thế nào để ${subject}?`, summary: `Câu trả lời nhanh về ${subject}.`, content: `Để xử lý ${subject}, khách hàng cần cung cấp thông tin liên quan và làm theo hướng dẫn hiển thị. Nếu yêu cầu liên quan giao dịch cụ thể, OmniCare phải xác minh customer, order và trạng thái hiện tại trước khi kết luận.`, version: "1.0.0" });
  }
  for (let index = 1; index <= 0; index += 1) {
    const categoryId = categories[index % categories.length][0];
    await upsertKnowledge({ id: `guide_${String(index).padStart(3, "0")}`, type: "GUIDE", visibility: "PUBLIC", categoryId: categoryIds.get(categoryId), authority: 75, title: `Hướng dẫn thao tác ${index}: ${categories[index % categories.length][2]}`, summary: "Hướng dẫn xử lý theo từng bước.", content: `Bước 1: xác định yêu cầu. Bước 2: chuẩn bị mã tham chiếu. Bước 3: kiểm tra trạng thái. Bước 4: liên hệ nhân viên nếu dữ liệu không đủ. Hướng dẫn số ${index}.` });
  }
  for (let index = 1; index <= 0; index += 1) {
    await upsertKnowledge({ id: `product_guide_${String(index).padStart(3, "0")}`, type: "PRODUCT_GUIDE", visibility: "PUBLIC", categoryId: categoryIds.get("warranty"), authority: 80, title: `Hướng dẫn sản phẩm ${index}`, summary: "Thông tin sử dụng và bảo quản sản phẩm.", content: `Hướng dẫn sản phẩm ${index}: kiểm tra nguồn điện, kết nối, phiên bản và điều kiện môi trường trước khi yêu cầu bảo hành.` });
  }
  for (let index = 1; index <= 0; index += 1) {
    await upsertKnowledge({ id: `troubleshooting_${String(index).padStart(3, "0")}`, type: "TROUBLESHOOTING", visibility: "PUBLIC", categoryId: categoryIds.get("warranty"), authority: 78, title: `Khắc phục sự cố sản phẩm ${index}`, summary: "Quy trình chẩn đoán và khắc phục sự cố.", content: `Sự cố ${index}: khởi động lại thiết bị, kiểm tra kết nối, cập nhật phiên bản và ghi nhận mã lỗi. Không tháo thiết bị nếu còn bảo hành.` });
  }
  for (let index = 1; index <= 0; index += 1) {
    const categoryId = categories[index % categories.length][0];
    await upsertKnowledge({ id: `sop_${String(index).padStart(3, "0")}`, type: "SOP", visibility: "INTERNAL", categoryId: categoryIds.get(categoryId), authority: 60, title: `SOP nội bộ ${index}`, summary: "Quy trình vận hành nội bộ.", content: `SOP ${index}: xác minh danh tính, thu thập bằng chứng, kiểm tra quyền, tạo gói chuyển tiếp và ghi audit. Không tiết lộ nội dung này cho khách.` });
  }
  for (let index = 1; index <= 50; index += 1) {
    const active = index <= 3;
    await upsertKnowledge({ id: `incident_doc_${String(index).padStart(2, "0")}`, type: "INCIDENT", visibility: "PUBLIC", categoryId: categoryIds.get("status"), authority: 98, title: `Thông báo dịch vụ ${index}`, summary: active ? "Sự cố demo đang được theo dõi." : "Sự cố demo đã khôi phục.", content: active ? `Một phần dịch vụ demo số ${index} đang chậm. Đội vận hành đang xử lý.` : `Dịch vụ demo số ${index} đã được khôi phục.`, version: "1.0.0" });
    await prisma.serviceIncident.upsert({ where: { id: `incident_${index}` }, update: {}, create: { id: `incident_${index}`, title: `Sự cố dịch vụ ${index}`, description: `Theo dõi ảnh hưởng dịch vụ số ${index}`, status: active ? "ACTIVE" : "RESOLVED", severity: index === 1 ? "HIGH" : "MEDIUM", startsAt: new Date(seedNow.getTime() - index * 3600000), endsAt: active ? null : seedNow, scope: { channels: index % 2 ? ["WEB"] : ["EMAIL"], categories: ["shipping", "payment"] } } });
  }
  for (let index = 1; index <= 0; index += 1) {
    const categoryId = categories[index % categories.length][0];
    await upsertKnowledge({ id: `historical_${String(index).padStart(3, "0")}`, type: "HISTORICAL_RESOLUTION", visibility: "INTERNAL", categoryId: categoryIds.get(categoryId), authority: 20, title: `Tình huống lịch sử ${index}`, summary: "Cách xử lý tham khảo, không phải nguồn chính sách.", content: `Tình huống tương tự số ${index} được giải quyết bằng cách xác minh dữ liệu, áp dụng chính sách đang hiệu lực và chuyển người khi thiếu bằng chứng.` });
  }
}

async function replaceSyntheticKnowledge() {
  const syntheticPrefixes = ["policy_0", "terms_", "faq_", "guide_", "product_guide_", "troubleshooting_", "sop_", "historical_"];
  const synthetic = await prisma.knowledgeDocument.findMany({ where: { OR: syntheticPrefixes.map((prefix) => ({ id: { startsWith: prefix } })) }, select: { id: true } });
  const ids = synthetic.map((item) => item.id);
  if (ids.length) {
    await prisma.knowledgeChunk.updateMany({ where: { version: { documentId: { in: ids } } }, data: { retrievalEnabled: false } });
    await prisma.knowledgeVersion.updateMany({ where: { documentId: { in: ids } }, data: { searchable: false, status: "ARCHIVED" } });
    await prisma.knowledgeDocument.updateMany({ where: { id: { in: ids } }, data: { archivedAt: seedNow } });
  }

  const categoryRows = await prisma.knowledgeCategory.findMany();
  const categoryIds = new Map(categoryRows.map((category) => [category.id, category.id]));
  const states = [
    ["PENDING", "đơn đang chờ xác nhận", "kiểm tra thanh toán và cho phép hủy nếu chưa bắt đầu xử lý"],
    ["PROCESSING", "đơn đang được chuẩn bị", "xác minh khả năng hủy trước khi kho bàn giao vận chuyển"],
    ["SHIPPED", "đơn đã bàn giao đơn vị vận chuyển", "tra cứu hành trình và mở điều tra nếu quá ETA"],
    ["OUT_FOR_DELIVERY", "đơn đang được giao", "kiểm tra lần giao gần nhất và hướng dẫn nhận hàng"],
    ["DELIVERED", "đơn đã giao", "kiểm tra bằng chứng giao, thời hạn đổi trả và trạng thái hoàn tiền"],
  ];
  const evidenceByCategory = {
    account: "email hoặc số điện thoại đã che",
    orders: "mã đơn và sản phẩm cần xử lý",
    shipping: "mã đơn, tracking và sự kiện giao hàng",
    payment: "mã đơn và mã giao dịch đã che",
    refund: "mã đơn, lý do và ảnh/video sản phẩm",
    voucher: "mã voucher, thời điểm áp dụng và giỏ hàng",
    warranty: "mã đơn, serial và mô tả lỗi",
    dispute: "mã đơn, nội dung tranh chấp và bằng chứng",
    legal: "loại yêu cầu dữ liệu và danh tính đã xác minh",
    status: "kênh, thời điểm lỗi và mã tham chiếu",
  };
  let documentIndex = 0;
  for (const [categoryId] of categories) {
    const subjects = categorySubjects[categoryId];
    for (const subject of subjects.slice(0, 1)) {
      for (const [state, stateText, action] of states.slice(0, 1)) {
        documentIndex += 1;
        const id = `curated_${String(documentIndex).padStart(4, "0")}`;
        const title = `${subject.charAt(0).toUpperCase()}${subject.slice(1)} khi ${stateText}`;
        const content = `Tình huống áp dụng: ${stateText}. Mục tiêu hỗ trợ: ${subject}. Dữ liệu bắt buộc: ${evidenceByCategory[categoryId]}. Agent phải dùng tool để xác minh dữ liệu hiện tại, sau đó ${action}. Không kết luận quyền lợi hoặc trạng thái nếu tool chưa trả SUCCESS. Nếu ownership không hợp lệ, evidence thiếu hoặc policy mâu thuẫn thì dừng thao tác và chuyển nhân viên.`;
        await upsertKnowledge({ id, type: documentIndex % 5 === 0 ? "GUIDE" : "FAQ", visibility: "PUBLIC", categoryId: categoryIds.get(categoryId), authority: documentIndex % 5 === 0 ? 80 : 75, title, summary: `Hướng dẫn ${subject} cho trạng thái ${state}.`, content, version: "2026.1" });
      }
    }
  }
}

async function seedSupport() {
  for (let index = 1; index <= 8; index += 1) {
    const customerId = `customer_${String(((index - 1) % 2) + 1).padStart(3, "0")}`;
    const orderId = `ORD-${1000 + index}`;
    const conversationId = `conv_history_${String(index).padStart(3, "0")}`;
    const ticketId = `TCK-${String(1000 + index)}`;
    await prisma.conversation.upsert({ where: { id: conversationId }, update: {}, create: { id: conversationId, customerId, channel: index % 2 ? "WEB" : "EMAIL", externalId: `thread_${index}` } });
    await prisma.message.upsert({ where: { id: `msg_history_${index}` }, update: {}, create: { id: `msg_history_${index}`, conversationId, direction: "INBOUND", content: `Yêu cầu hỗ trợ cho đơn ${orderId}` } });
    await prisma.ticket.upsert({ where: { id: ticketId }, update: {}, create: { id: ticketId, customerId, orderId, conversationId, status: index % 4 === 0 ? "NEED_HUMAN" : "RESOLVED", priority: ["LOW", "MEDIUM", "HIGH", "URGENT"][index % 4], category: categories[index % categories.length][0], summary: `Yêu cầu hỗ trợ ${index}` } });
  }
}

async function seedSupplementalKnowledge() {
  await upsertKnowledge({
    id: "kb_app_support_core",
    type: "TROUBLESHOOTING",
    visibility: "PUBLIC",
    categoryId: "account",
    authority: 95,
    title: "Khắc phục lỗi ứng dụng Omni",
    summary: "Các bước an toàn khi ứng dụng lỗi, bị văng, không nhận thông báo hoặc cần cập nhật.",
    content: "Khi ứng dụng Omni gặp lỗi, hãy kiểm tra kết nối mạng, đóng và mở lại ứng dụng, sau đó cập nhật ứng dụng lên phiên bản mới nhất từ kho ứng dụng chính thức. Nếu ứng dụng bị văng hoặc hoạt động chậm, có thể xóa bộ nhớ đệm rồi đăng nhập lại; không cài phần mềm hoặc tệp từ nguồn lạ. Nếu không nhận được thông báo, kiểm tra quyền thông báo của ứng dụng và chế độ tiết kiệm pin trên thiết bị. Nếu lỗi vẫn còn, ghi lại mã lỗi, thời điểm xảy ra và ảnh chụp màn hình để nhân viên hỗ trợ kiểm tra.",
    version: "2026.1",
  });
}

async function main() {
  if (process.env.SEED_ALLOW_RESET === "true") {
    await prisma.$executeRawUnsafe('TRUNCATE TABLE "UserAccount", "Customer", "Product", "KnowledgeCategory", "ServiceIncident", "Conversation" RESTART IDENTITY CASCADE');
  }
  await seedCommerce();
  await seedReturnRules();
  await seedAccounts();
  await seedKnowledge();
  await replaceSyntheticKnowledge();
  await seedSupport();
  await seedSupplementalKnowledge();
  const counts = {
    customers: await prisma.customer.count(),
    orders: await prisma.order.count(),
    documents: await prisma.knowledgeDocument.count(),
    tickets: await prisma.ticket.count(),
    incidents: await prisma.serviceIncident.count(),
  };
  console.log(JSON.stringify(counts));
}

main().finally(() => prisma.$disconnect());
