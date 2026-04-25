export type SessionSummary = {
  session_id: string;
  created_at: string;
  title: string;
};

export type ToolStatus = "running" | "ok" | "error";

export type ToolCall = {
  id: string;
  name: string;          // raw, e.g. "create_contact"
  status: ToolStatus;
};

export type Message = {
  id: string;            // client-generated uuid
  role: "user" | "assistant";
  content: string;
  tools: ToolCall[];     // only meaningful on assistant
};

export type HistoricalMessage = {
  role: "user" | "assistant";
  content: string | null;
  tool_calls:
    | { id: string; name: string; arguments: unknown }[]
    | null;
};
