export interface PairRequest {
  device_id: string;
  public_key_b64: string;
  pairing_code: string;
  code_signature_b64: string;
}

export interface SessionBeginRequest {
  device_id: string;
}

export interface SessionBeginResponse {
  nonce_b64: string;
}

export interface SessionCompleteRequest {
  device_id: string;
  nonce_b64: string;
  counter: number;
  signature_b64: string;
}

export interface SessionCompleteResponse {
  session_token: string;
  expires_at: number;
}

// Wire contract: the unlock-begin request body is an empty JSON object.
// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface UnlockBeginRequest {}

export interface UnlockBeginResponse {
  nonce_b64: string;
}

export interface UnlockCompleteRequest {
  nonce_b64: string;
  counter: number;
  signature_b64: string;
}

export interface StatusResponse {
  connected: boolean;
  vault_unlocked: boolean;
  device_id: string;
}

export interface AskRequest {
  text: string;
}

export interface AskResponse {
  text: string;
  path: string;
  tool_used?: string | null;
  escalated: boolean;
}

export interface ReviewItem {
  name: string;
  description: string;
  status: string;
  action_class: string;
  safety: string;
  explanation: string;
}

export interface CardPlacement {
  id: string;
  domain: string;
  cluster: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LayoutDTO {
  version: number;
  updated_at: string;
  cards: CardPlacement[];
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  kind: string;
  attendees?: string[] | null;
  rsvp?: string | null;
}

export interface CalendarRead {
  events: CalendarEvent[];
  tasks_due_by_day: Record<string, number>;
}

export interface TasksRead {
  overdue: string[];
  today: string[];
  upcoming: string[];
  suggestions: string[];
}

export interface ProjectItem {
  id: string;
  name: string;
  status: string;
  target?: string | null;
  open_tasks: number;
}

export interface ProjectsRead {
  projects: ProjectItem[];
}

export interface GmailNeed {
  id: string;
  sender: string;
  subject: string;
  why: string;
}

export interface GmailSignal {
  id: string;
  sender: string;
  subject: string;
  ts: string;
}

export interface GmailRead {
  needs_you: GmailNeed[];
  signal: GmailSignal[];
}

export interface FinanceDaily {
  date: string;
  amount: number;
}

export interface FinanceCategory {
  name: string;
  amount: number;
  color: string;
}

export interface FinanceTransaction {
  id: string;
  merchant: string;
  amount: number;
  date: string;
  category: string;
}

export interface FinanceBill {
  id: string;
  name: string;
  amount: number;
  due: string;
}

export interface FinanceRead {
  week_total: number;
  mtd_total: number;
  daily: FinanceDaily[];
  categories: FinanceCategory[];
  transactions: FinanceTransaction[];
  bills: FinanceBill[];
  unusual?: string[] | null;
  duplicate?: string[] | null;
  ambiguous?: string[] | null;
}

export type ConnectionState = "unpaired" | "disconnected" | "connectedLocked" | "unlocked";

export type StreamEvent =
  | { type: "text"; text: string }
  | { type: "vault_locked" }
  | { type: "done"; path?: string; tool_used?: string; escalated?: boolean };

export interface OkResponse {
  ok: boolean;
}
