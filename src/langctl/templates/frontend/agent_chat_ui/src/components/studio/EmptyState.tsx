"use client";

import { TriangleAlertIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function EmptyState({ path }: { path: string }) {
  return (
    <Alert className="m-4">
      <TriangleAlertIcon />
      <AlertTitle>No agent.yaml found</AlertTitle>
      <AlertDescription>
        {path} doesn&apos;t look like a langctl project — opening it anyway,
        but nothing here was scaffolded by langctl.
      </AlertDescription>
    </Alert>
  );
}
