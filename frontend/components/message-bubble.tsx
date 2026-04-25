import { ToolChip } from "./tool-chip";
import type { Message } from "@/lib/types";

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} my-2`}
    >
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-gray-100 text-gray-900"
        }`}
      >
        {message.content && (
          <div className="whitespace-pre-wrap break-words">
            {message.content}
          </div>
        )}
        {!isUser && message.tools.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.tools.map((t) => (
              <ToolChip key={t.id} tool={t} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
