export type SessionSummary = {
  session_id: string;
  created_at: string;
  title: string;
};

export type Citation = {
  doc_id: string;
  filename: string;
  page_no: number;
  snippet: string;
  score: number;
};

export type Document = {
  document_id: string;
  filename: string;
  page_count: number;
  progress_page: number;
  status: "processing" | "ready" | "failed";
  error_message?: string | null;
  uploaded_at?: string | null;
};

export type ToolStatus = "running" | "ok" | "error";

export type ToolCall = {
  id: string;
  name: string;          // raw, e.g. "search_documents"
  status: ToolStatus;
};

export type ToolChip = { id: string; name: string; status: ToolStatus };

export type Message = {
  id: string;            // client-generated uuid
  role: "user" | "assistant";
  content: string;
  tools: ToolCall[];     // only meaningful on assistant
  citations?: Citation[];
};

export type HistoricalMessage = {
  role: "user" | "assistant";
  content: string | null;
  tool_calls:
    | { id: string; name: string; arguments: unknown }[]
    | null;
};
