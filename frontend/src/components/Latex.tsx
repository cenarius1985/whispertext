"use client";

import { useMemo } from "react";
import katex from "katex";

/** Render LaTeX (reconstruido por Bonsai) con KaTeX; fallback a código. */
export default function Latex({ tex }: { tex: string }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { displayMode: true, throwOnError: false });
    } catch {
      return `<code>${tex.replace(/</g, "&lt;")}</code>`;
    }
  }, [tex]);
  return (
    <div
      className="my-1 overflow-x-auto rounded-lg bg-slate-50 px-3 py-2 text-slate-800 ring-1 ring-slate-100"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
