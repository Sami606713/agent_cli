"use client";

import React, { useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";
import { FolderOpenIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Explorer } from "@/components/studio/Explorer";
import { Viewer } from "@/components/studio/Viewer";
import { EmptyState } from "@/components/studio/EmptyState";
import { ChatPanel } from "@/components/studio/ChatPanel";
import { buildTree, hasAgentSpec, type TreeNode } from "@/lib/studio-tree";
import { readFile, type FileContent } from "@/lib/studio-read-file";

/** Pulls `name: ...` out of agent.yaml without a full YAML parser. */
function extractProjectName(yamlText: string): string | null {
  const match = yamlText.match(/^name:\s*"?([^"\n]+)"?\s*$/m);
  return match ? match[1].trim() : null;
}

function StudioScreen() {
  const searchParams = useSearchParams();
  const pathHint = searchParams.get("path") ?? "the project you ran `langctl studio` from";

  const [nodes, setNodes] = useState<TreeNode[] | null>(null);
  const [isProject, setIsProject] = useState(true);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [selected, setSelected] = useState<Extract<TreeNode, { kind: "file" }> | null>(null);
  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [error, setError] = useState<string | null>(null);

  const openFolder = useCallback(async () => {
    setError(null);
    try {
      // Not supported in every browser (Firefox, Safari) — surfaced plainly
      // rather than failing silently, since there is no server-side fallback.
      // `showDirectoryPicker` is a global (not a `Window` member) per the
      // wicg-file-system-access type definitions.
      if (typeof showDirectoryPicker !== "function") {
        setError(
          "This browser doesn't support opening local folders. Try Chrome or Edge.",
        );
        return;
      }
      const dirHandle = await showDirectoryPicker();
      const tree = await buildTree(dirHandle);
      setNodes(tree);
      setIsProject(hasAgentSpec(tree));

      const agentYaml = tree.find(
        (node): node is Extract<TreeNode, { kind: "file" }> =>
          node.kind === "file" && node.name === "agent.yaml",
      );
      if (agentYaml) {
        const { content } = await readFile(agentYaml.handle);
        setProjectName(extractProjectName(content));
      } else {
        setProjectName(dirHandle.name);
      }
    } catch (err) {
      // The user cancelling the picker throws AbortError — not a real error.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const onSelectFile = useCallback(async (node: Extract<TreeNode, { kind: "file" }>) => {
    setSelected(node);
    const content = await readFile(node.handle);
    setFileContent(content);
  }, []);

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex items-center justify-between border-b px-4 py-2.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          <span className="text-[#2F6868]">◆</span>
          <span>{projectName ?? "Studio"}</span>
        </div>
        {nodes && (
          <Badge variant="outline" className="text-muted-foreground">
            {pathHint}
          </Badge>
        )}
      </header>

      {!nodes ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="flex max-w-md flex-col items-center gap-4 rounded-xl border bg-card p-8 text-center shadow-sm">
            <FolderOpenIcon className="size-8 text-[#2F6868]" />
            <div>
              <p className="font-medium">Open a project</p>
              <p className="mt-1 font-mono text-sm break-all text-muted-foreground">
                {pathHint}
              </p>
            </div>
            <Button onClick={openFolder}>Open in Studio</Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        </div>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          {!isProject && <EmptyState path={pathHint} />}
          <ResizablePanelGroup direction="horizontal" className="flex-1">
            <ResizablePanel defaultSize={20} minSize={15} maxSize={40}>
              <Explorer
                nodes={nodes}
                selectedPath={selected?.path ?? null}
                onSelectFile={onSelectFile}
              />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={55}>
              <Viewer fileName={selected?.name ?? null} file={fileContent} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={25} minSize={20} maxSize={40}>
              <ChatPanel />
            </ResizablePanel>
          </ResizablePanelGroup>
        </div>
      )}
    </div>
  );
}

export default function StudioPage() {
  return (
    <React.Suspense fallback={<div>Loading…</div>}>
      <StudioScreen />
    </React.Suspense>
  );
}
