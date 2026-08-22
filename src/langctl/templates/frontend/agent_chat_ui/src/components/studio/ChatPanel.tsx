"use client";

import { useState } from "react";
import { MessageCircleIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChatBar } from "@/components/studio/ChatBar";

interface Message {
  role: "user" | "assistant";
  content: string;
}

/** Canned replies — there is no deep agent behind this yet (see phase-two plan). */
const DUMMY_REPLIES = [
  "Got it — once chat-driven editing is wired up, this is where I'd make that change.",
  "Noted. For now this is just a preview of the interaction — no files have actually changed.",
  "This is a dummy reply. The real version will read your project and edit it for real.",
];

/**
 * The right-hand chat sidebar. Sending a message works and gets a reply —
 * the reply is canned, not a real deep agent, so the interaction shape can
 * be previewed before anything real is wired behind it.
 */
export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);

  function handleSend(text: string) {
    const reply = DUMMY_REPLIES[messages.length % DUMMY_REPLIES.length];
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: reply },
    ]);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-2.5 text-sm font-medium text-foreground/90">
        Chat
      </div>
      <ScrollArea className="flex-1">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-muted-foreground">
            <MessageCircleIcon className="size-6" />
            <p className="text-sm">
              Chat-driven editing isn&apos;t wired up yet — try sending a
              message to preview the interaction.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3 p-3">
            {messages.map((message, i) => (
              <div
                key={i}
                className={cn(
                  "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                  message.role === "user"
                    ? "self-end bg-[#2F6868] text-white"
                    : "self-start bg-muted text-foreground",
                )}
              >
                {message.content}
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
      <ChatBar onSend={handleSend} />
    </div>
  );
}
