import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Class-name helper every shadcn-registry component imports from "@/lib/utils".
 * Shipped in the template so the AI Elements CLI has its prerequisite present
 * and never has to run `shadcn init` against a bare project.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
