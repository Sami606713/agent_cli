/** Reads a file's content client-side, for `/studio`'s read-only Viewer. */

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  py: "python",
  ts: "tsx",
  tsx: "tsx",
  js: "tsx",
  jsx: "tsx",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  md: "markdown",
  sh: "bash",
  txt: "text",
};

export function languageFor(name: string): string {
  if (name.startsWith(".env")) {
    return "bash";
  }
  const ext = name.includes(".") ? (name.split(".").pop() ?? "") : "";
  return LANGUAGE_BY_EXTENSION[ext] ?? "text";
}

export interface FileContent {
  content: string;
  language: string;
}

export async function readFile(handle: FileSystemFileHandle): Promise<FileContent> {
  const file = await handle.getFile();
  const content = await file.text();
  return { content, language: languageFor(file.name) };
}
