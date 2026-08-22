"use client";

import { useState } from "react";
import {
  ChevronRightIcon,
  FileIcon,
  FileJsonIcon,
  FileTextIcon,
  FolderIcon,
  FolderOpenIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { TreeNode } from "@/lib/studio-tree";

function iconFor(name: string) {
  const ext = name.includes(".") ? name.split(".").pop() : undefined;
  if (ext === "json" || ext === "yaml" || ext === "yml") return FileJsonIcon;
  if (ext === "md" || name.startsWith(".env")) return FileTextIcon;
  return FileIcon;
}

function Node({
  node,
  depth,
  selectedPath,
  onSelectFile,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  onSelectFile: (node: Extract<TreeNode, { kind: "file" }>) => void;
}) {
  const [open, setOpen] = useState(depth === 0);
  const indent = { paddingLeft: `${depth * 14 + 8}px` };

  if (node.kind === "directory") {
    return (
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger
          className="flex w-full items-center gap-1.5 rounded-sm py-1 text-sm text-foreground/80 hover:bg-accent hover:text-accent-foreground"
          style={indent}
        >
          <ChevronRightIcon
            className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")}
          />
          {open ? (
            <FolderOpenIcon className="size-3.5 shrink-0 text-[#2F6868]" />
          ) : (
            <FolderIcon className="size-3.5 shrink-0 text-[#2F6868]" />
          )}
          <span className="truncate">{node.name}</span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          {node.children.map((child) => (
            <Node
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelectFile={onSelectFile}
            />
          ))}
        </CollapsibleContent>
      </Collapsible>
    );
  }

  const Icon = iconFor(node.name);
  const selected = node.path === selectedPath;

  return (
    <button
      type="button"
      onClick={() => onSelectFile(node)}
      className={cn(
        "flex w-full items-center gap-1.5 rounded-sm py-1 pr-2 text-left text-sm hover:bg-accent hover:text-accent-foreground",
        selected ? "bg-accent text-accent-foreground" : "text-foreground/80",
      )}
      style={indent}
    >
      <Icon className="ml-[18px] size-3.5 shrink-0" />
      <span className="truncate">{node.name}</span>
      {selected && (
        <span className="ml-auto size-1.5 shrink-0 rounded-full bg-[#2F6868]" />
      )}
    </button>
  );
}

export function Explorer({
  nodes,
  selectedPath,
  onSelectFile,
}: {
  nodes: TreeNode[];
  selectedPath: string | null;
  onSelectFile: (node: Extract<TreeNode, { kind: "file" }>) => void;
}) {
  return (
    <ScrollArea className="h-full">
      <div className="px-2 py-2">
        <p className="px-2 pb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Explorer
        </p>
        {nodes.map((node) => (
          <Node
            key={node.path}
            node={node}
            depth={0}
            selectedPath={selectedPath}
            onSelectFile={onSelectFile}
          />
        ))}
      </div>
    </ScrollArea>
  );
}
