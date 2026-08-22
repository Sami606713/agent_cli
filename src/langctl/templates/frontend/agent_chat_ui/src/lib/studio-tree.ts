/**
 * Walks a FileSystemDirectoryHandle into an in-memory tree, entirely
 * client-side, for the `/studio` route — no request ever carries a
 * directory listing anywhere.
 */

export type TreeNode =
  | {
      kind: "directory";
      name: string;
      path: string;
      handle: FileSystemDirectoryHandle;
      children: TreeNode[];
    }
  | {
      kind: "file";
      name: string;
      path: string;
      handle: FileSystemFileHandle;
    };

/** Real noise in every real project — hidden unless explicitly requested. */
const DEFAULT_HIDDEN = new Set([".venv", "__pycache__", ".git", "node_modules"]);

function isHidden(name: string): boolean {
  return DEFAULT_HIDDEN.has(name);
}

function compareNodes(a: TreeNode, b: TreeNode): number {
  if (a.kind !== b.kind) {
    return a.kind === "directory" ? -1 : 1;
  }
  return a.name.localeCompare(b.name);
}

export async function buildTree(
  dirHandle: FileSystemDirectoryHandle,
  options: { showHidden?: boolean } = {},
  parentPath = "",
): Promise<TreeNode[]> {
  const showHidden = options.showHidden ?? false;
  const nodes: TreeNode[] = [];

  for await (const [name, handle] of dirHandle.entries()) {
    if (!showHidden && isHidden(name)) {
      continue;
    }

    const path = parentPath ? `${parentPath}/${name}` : name;

    if (handle.kind === "directory") {
      const children = await buildTree(handle, options, path);
      nodes.push({ kind: "directory", name, path, handle, children });
    } else {
      nodes.push({ kind: "file", name, path, handle });
    }
  }

  nodes.sort(compareNodes);
  return nodes;
}

/** True when the picked folder looks like a langctl project. */
export function hasAgentSpec(nodes: TreeNode[]): boolean {
  return nodes.some((node) => node.kind === "file" && node.name === "agent.yaml");
}
