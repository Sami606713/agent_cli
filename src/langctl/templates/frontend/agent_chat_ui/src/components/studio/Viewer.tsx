"use client";

import { PrismAsyncLight as SyntaxHighlighterPrism } from "react-syntax-highlighter";
import { coldarkCold } from "react-syntax-highlighter/dist/cjs/styles/prism";

import { ScrollArea } from "@/components/ui/scroll-area";
// Registers python/tsx/json/yaml/bash/markdown once, as a side effect of
// this import — reused rather than re-registering the same languages here.
import "@/components/thread/syntax-highlighter";
import type { FileContent } from "@/lib/studio-read-file";

export function Viewer({
  fileName,
  file,
}: {
  fileName: string | null;
  file: FileContent | null;
}) {
  if (!fileName || !file) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a file to view it.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-2 text-sm font-medium text-foreground/90">
        {fileName}
      </div>
      <ScrollArea className="flex-1">
        {/*
          The shared chat-UI SyntaxHighlighter is hard-wired to a dark theme
          (coldarkDark) meant to sit on the dark code-block background used
          in chat messages. Studio's page is the app's normal light
          background, so this uses coldarkCold — the light sibling of the
          same theme — directly, rather than forcing a dark panel here.
        */}
        <SyntaxHighlighterPrism
          language={file.language}
          style={coldarkCold}
          customStyle={{
            margin: 0,
            width: "100%",
            background: "transparent",
            padding: "1rem 1.25rem",
          }}
        >
          {file.content}
        </SyntaxHighlighterPrism>
      </ScrollArea>
    </div>
  );
}
