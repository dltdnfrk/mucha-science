import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { isSafeExternalHttpUrl } from "../lib/safeExternalUrl";

interface SafeReportMarkdownProps {
  readonly markdown: string;
}

export function SafeReportMarkdown({
  markdown,
}: SafeReportMarkdownProps) {
  return (
    <ReactMarkdown
      components={{ a: SafeMarkdownAnchor }}
      remarkPlugins={[remarkGfm]}
      urlTransform={safeMarkdownUrlTransform}
    >
      {markdown}
    </ReactMarkdown>
  );
}

function SafeMarkdownAnchor({
  children,
  href,
}: ComponentPropsWithoutRef<"a">) {
  return href && isSafeExternalHttpUrl(href)
    ? <a href={href} rel="noreferrer" target="_blank">{children}</a>
    : <span>{children}</span>;
}

function safeMarkdownUrlTransform(url: string): string {
  return isSafeExternalHttpUrl(url) ? url : "";
}
