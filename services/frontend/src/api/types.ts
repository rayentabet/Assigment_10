// Mirrors app/api/schemas.py. Keep these two files in sync by hand; there is
// no shared schema generation step in this project.

export interface ThreadResponse {
  thread_id: string;
}

export interface ThreadSummary {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ThreadListResponse {
  threads: ThreadSummary[];
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface WiringPlanComponent {
  component: string;
  display_name: string;
  pins: Record<string, string | number>;
}

export interface WiringPlan {
  board: string;
  valid: boolean;
  components: WiringPlanComponent[];
  conflicts: string[];
  warnings: string[];
  table_markdown: string;
}

export interface PurchaseProposal {
  question: string;
  proposal_id: string;
  component_id: string;
  component_name: string | null;
  quantity: number;
  supplier_name: string | null;
  unit_price: number;
  currency: string;
  fees: number | null;
  total: number;
  delivery_estimate_days: number | null;
  expires_at: string;
}

export interface PurchaseReference {
  proposal_id: string | null;
  order_id: string | null;
  status: string | null;
}

export interface ProductCard {
  supplier: string;
  digikey_part_number: string | null;
  manufacturer_part_number: string | null;
  manufacturer: string | null;
  description: string | null;
  quantity_available: number;
  requested_quantity: number;
  unit_price: number | null;
  total_price: number | null;
  currency: string;
  product_url: string | null;
  image_url: string | null;
  datasheet_url: string | null;
}

export interface DigiKeyConnectionStatus {
  configured: boolean;
  connected: boolean;
  sandbox: boolean;
  expires_at: number | null;
}

export interface PaymentCredential {
  payment_method_id: string;
  display: string;
  brand: string;
  last4: string | null;
  sandbox: boolean;
}

export interface PaymentConfig {
  provider: "sandbox" | "lithic";
}

export interface SandboxCard {
  card_number: string;
  expiry: string;
  cvv: string;
}

export interface ApprovalRequest {
  question: string;
  action: string;
  task: string;
  reason: string;
}

export interface ToolTraceEntry {
  agent: string;
  event: "call" | "result";
  tool: string;
  arguments: Record<string, unknown> | null;
  content: string | null;
  tool_call_id: string | null;
}

export type ChatStatus = "completed" | "approval_required";

export interface ChatResponse {
  thread_id: string;
  status: ChatStatus;
  answer: string | null;
  approval: ApprovalRequest | null;
  purchase_proposal: PurchaseProposal | null;
  image_urls: string[];
  wiring_plan: WiringPlan | null;
  purchase_reference: PurchaseReference | null;
  product_cards: ProductCard[];
  tool_trace: ToolTraceEntry[];
  route_history: string[];
}

// Mirrors app/api/main.py's STREAM_UPDATE_FIELDS allowlist and _sse_frame.
export interface StreamNodeFrame {
  type: "node";
  node: string;
  update: Partial<{
    tool_trace: ToolTraceEntry[];
    route_history: string[];
    next_agent: string;
    completed_tasks: string[];
    project: Record<string, unknown>;
    final_answer: string | null;
    image_paths: string[];
    iteration_count: number;
    input_blocked: boolean;
  }>;
}

export interface StreamDoneFrame extends ChatResponse {
  type: "done";
}

export interface StreamErrorFrame {
  type: "error";
  message: string;
}

export type StreamFrame = StreamNodeFrame | StreamDoneFrame | StreamErrorFrame;

export interface TranscriptionResponse {
  text: string;
}

export interface ThreadHistoryResponse {
  thread_id: string;
  messages: HistoryMessage[];
  image_urls: string[];
  wiring_plan: WiringPlan | null;
  purchase_reference: PurchaseReference | null;
  product_cards: ProductCard[];
}
