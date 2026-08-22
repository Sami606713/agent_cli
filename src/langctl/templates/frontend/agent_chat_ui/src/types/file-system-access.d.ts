/**
 * Minimal ambient declarations for the File System Access API surface
 * `/studio` actually uses. Declared locally rather than relying solely on
 * `@types/wicg-file-system-access` resolving correctly in every consumer's
 * TypeScript setup — this file is guaranteed to be picked up because it
 * matches this project's own `include` glob.
 */

declare global {
  interface FileSystemHandle {
    readonly kind: "file" | "directory";
    readonly name: string;
  }

  interface FileSystemFileHandle extends FileSystemHandle {
    readonly kind: "file";
    getFile(): Promise<File>;
  }

  interface FileSystemDirectoryHandle extends FileSystemHandle {
    readonly kind: "directory";
    entries(): AsyncIterableIterator<
      [string, FileSystemFileHandle | FileSystemDirectoryHandle]
    >;
  }

  function showDirectoryPicker(): Promise<FileSystemDirectoryHandle>;
}

export {};
