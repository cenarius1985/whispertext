"""Regenera los PNG de ecuaciones/figuras de un documento a DPI alto,
sobrescribiendo las rutas ya registradas (sin tocar la BD).

Uso (dentro del worker): python -m regen_images <doc_id>
"""

import asyncio
import sys

from sqlalchemy import select

from wispertext.db import get_sessionmaker
from wispertext.models import Document, Image, Paragraph
from wispertext.worker.extractors import extract_any


async def main(doc_id: str) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            sys.exit("documento no existe")
        ex = extract_any(doc.archivo_original)
        rows = (
            (
                await session.execute(
                    select(Paragraph.indice, Image.ruta)
                    .join(Image, Image.paragraph_id == Paragraph.id)
                    .where(Paragraph.document_id == doc.id, Paragraph.activo.is_(True))
                    .order_by(Paragraph.indice)
                )
            )
            .all()
        )
        n = 0
        for indice, ruta in rows:
            bloque = ex.bloques[indice] if indice < len(ex.bloques) else None
            if bloque and bloque.image_bytes:
                with open(ruta, "wb") as fh:
                    fh.write(bloque.image_bytes)
                n += 1
        print(f"regenerados {n}/{len(rows)} PNG de {doc.titulo[:40]}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
