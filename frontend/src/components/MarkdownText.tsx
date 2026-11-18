"use client";

import { useMemo, type ReactNode } from "react";
import katex from "katex";

/**
 * Markdown mínimo para el lector (docs/12): $..$ / $$..$$ → KaTeX,
 * tablas | .. |, **negrita**, *cursiva*, `código`, ### subtítulos y listas.
 * Sin deps nuevas: la entrada SIEMPRE se escapa; el único HTML que se genera
 * es el propio del renderer + el de KaTeX (que es seguro por diseño).
 */

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function katexHtml(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: false });
  } catch {
    return `<code>${esc(tex)}</code>`;
  }
}

/** Énfasis inline sobre texto YA escapado. */
function enfasis(s: string): string {
  return s
    .replace(/`([^`]+)`/g, '<code class="rounded bg-slate-100 px-1 text-[13px]">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s.,;:)])/g, "$1<em>$2</em>");
}

/** Una línea de texto con matemática inline $..$ (no $$). */
function inlineMd(s: string): string {
  const partes = s.split(/(\$[^$\n]+\$)/g);
  return partes
    .map((p) =>
      p.length > 2 && p.startsWith("$") && p.endsWith("$")
        ? katexHtml(p.slice(1, -1), false)
        : enfasis(p)
    )
    .join("");
}

function tablaHtml(lineas: string[]): string {
  const celdas = (l: string) =>
    l
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((c) => `<td class="px-3 py-1.5">${inlineMd(c.trim())}</td>`)
      .join("");
  const esSeparador = (l: string) => /^\|?[\s:|-]+\|?$/.test(l);
  const filas = lineas.filter((l) => !esSeparador(l));
  if (!filas.length) return esc(lineas.join("\n"));
  const [encabezado, ...cuerpo] = filas;
  return (
    '<div class="my-2 overflow-x-auto"><table class="w-full border-collapse text-sm ring-1 ring-slate-200 rounded-lg">' +
    `<thead><tr class="bg-slate-50 border-b border-slate-200">${celdas(encabezado).replace(
      /<td/g,
      '<th class="px-3 py-1.5 text-left font-semibold"'
    )}</tr></thead>` +
    `<tbody>${cuerpo
      .map((l) => `<tr class="border-b border-slate-100">${celdas(l)}</tr>`)
      .join("")}</tbody></table></div>`
  );
}

function mdAHtml(md: string): string {
  const lineas = md.split("\n");
  const out: string[] = [];
  let buffer: string[] = []; // líneas de prosa acumuladas
  let i = 0;

  const flush = () => {
    if (!buffer.length) return;
    out.push(`<p class="my-0 leading-7">${inlineMd(buffer.join(" "))}</p>`);
    buffer = [];
  };

  while (i < lineas.length) {
    const l = lineas[i];

    // $$ display math (una o varias líneas). KaTeX no corta línea: sin
    // overflow-x la fórmula larga desborda la columna y se ve recortada.
    const dm = l.match(/^\s*\$\$(.+)\$\$\s*$/);
    if (dm) {
      flush();
      out.push(`<div class="my-2 overflow-x-auto">${katexHtml(dm[1], true)}</div>`);
      i++;
      continue;
    }
    if (/^\s*\$\$/.test(l)) {
      flush();
      const trozo: string[] = [l.replace(/^\s*\$\$/, "")];
      i++;
      while (i < lineas.length && !/\$\$/.test(lineas[i])) trozo.push(lineas[i++]);
      if (i < lineas.length) trozo.push(lineas[i++].replace(/\$\$\s*$/, ""));
      out.push(`<div class="my-2 overflow-x-auto">${katexHtml(trozo.join(" ").trim(), true)}</div>`);
      continue;
    }

    // tabla
    if (/^\s*\|.*\|/.test(l)) {
      flush();
      const t: string[] = [];
      while (i < lineas.length && /^\s*\|/.test(lineas[i])) t.push(lineas[i++]);
      out.push(tablaHtml(t));
      continue;
    }

    // encabezados
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      flush();
      const nivel = Math.min(h[1].length + 1, 5); // #→h2 … ####→h5
      out.push(`<h${nivel} class="mt-2 mb-1 font-semibold text-slate-900">${inlineMd(h[2])}</h${nivel}>`);
      i++;
      continue;
    }

    // listas
    if (/^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l)) {
      flush();
      const ordenada = /^\s*\d+\.\s/.test(l);
      const items: string[] = [];
      while (i < lineas.length && (/^\s*[-*]\s+/.test(lineas[i]) || /^\s*\d+\.\s+/.test(lineas[i]))) {
        items.push(`<li class="ml-4 list-${ordenada ? "decimal" : "disc"}">${inlineMd(lineas[i++].replace(/^\s*(?:[-*]|\d+\.)\s+/, ""))}</li>`);
      }
      out.push(`<${ordenada ? "ol" : "ul"} class="my-1 space-y-0.5">${items.join("")}</${ordenada ? "ol" : "ul"}>`);
      continue;
    }

    if (l.trim() === "") {
      flush();
      i++;
      continue;
    }
    buffer.push(l.trim());
    i++;
  }
  flush();
  return out.join("");
}

export default function MarkdownText({
  md,
  fallback,
  className = "",
}: {
  md?: string | null;
  fallback: ReactNode;
  className?: string;
}) {
  const html = useMemo(
    () => mdAHtml((md ?? "").trim() ? (md as string) : ""),
    [md]
  );
  if (!html) return <div className={className}>{fallback}</div>;
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
