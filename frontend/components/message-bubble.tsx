import type { Message } from "@/lib/types";
import { CitationCard } from "./citation-card";

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} my-2`}
    >
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed ${
          isUser
            ? "bg-indigo-600 text-white"
            : "border border-gray-200 bg-white text-gray-900 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
        }`}
      >
        {message.content && (
          <div className="whitespace-pre-wrap break-words">
            {message.content}
          </div>
        )}
        {message.role === "assistant" && message.citations && (
          <CitationCard citations={message.citations} />
        )}
      </div>
    </div>
  );
}
