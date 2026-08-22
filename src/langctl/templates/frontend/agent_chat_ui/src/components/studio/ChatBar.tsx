"use client";

import { useState } from "react";
import { SendIcon } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

/**
 * Placeholder for phase two's chat-driven editing. Typing and sending work
 * — the reply is a canned line, not a real deep agent — so the interaction
 * shape can be previewed before anything real is wired behind it.
 */
export function ChatBar({ onSend }: { onSend: (text: string) => void }) {
  const [value, setValue] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const text = value.trim();
        if (!text) return;
        onSend(text);
        setValue("");
      }}
      className="flex items-center gap-2 border-t p-2"
    >
      <Input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Ask Studio to change something…"
        className="h-8 text-xs"
      />
      <Button
        type="submit"
        size="icon"
        variant="ghost"
        disabled={!value.trim()}
        className="size-8 shrink-0"
      >
        <SendIcon className="size-3.5" />
      </Button>
    </form>
  );
}
