import type { ReactNode } from "react";

export function AdvancedFields({ title, children }: { title: string; summary?: ReactNode; children: ReactNode }) {
  return <section className="form-section"><h4>{title}</h4>{children}</section>;
}
