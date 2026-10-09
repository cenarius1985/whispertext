"""Rutas de categorías (colecciones N:M) — RF-CAT-02…06."""

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from wispertext.api.deps import get_session
from wispertext.api.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from wispertext.models import DocumentCategory, Category

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, "id inválido")


@router.get("", response_model=list[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_session)):
    """Lista con total de documentos por categoría (para el sidebar)."""
    totales = (
        await session.execute(
            select(
                DocumentCategory.c.category_id, func.count()
            ).group_by(DocumentCategory.c.category_id)
        )
    ).all()
    mapa = {str(cid): n for cid, n in totales}
    cats = (
        (await session.execute(select(Category).order_by(Category.es_sistema.desc(), Category.nombre)))
        .scalars()
        .all()
    )
    out = []
    for c in cats:
        o = CategoryOut.model_validate(c)
        o.total = mapa.get(str(c.id), 0)
        out.append(o)
    return out


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreate, session: AsyncSession = Depends(get_session)
):
    nombre = body.nombre.strip()
    dup = (
        await session.execute(
            select(Category).where(func.lower(Category.nombre) == nombre.lower())
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"categoría '{nombre}' ya existe")
    cat = Category(nombre=nombre, color=body.color, icono=body.icono)
    session.add(cat)
    await session.commit()
    out = CategoryOut.model_validate(cat)
    out.total = 0
    return out


@router.patch("/{cat_id}", response_model=CategoryOut)
async def update_category(
    cat_id: str,
    body: CategoryUpdate,
    session: AsyncSession = Depends(get_session),
):
    cat = await session.get(Category, _uuid(cat_id))
    if cat is None:
        raise HTTPException(404, "categoría no existe")
    if cat.es_sistema:
        raise HTTPException(400, "las categorías de sistema no se pueden editar")
    if body.nombre is not None:
        nombre = body.nombre.strip()
        dup = (
            await session.execute(
                select(Category).where(
                    func.lower(Category.nombre) == nombre.lower(),
                    Category.id != cat.id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(409, f"categoría '{nombre}' ya existe")
        cat.nombre = nombre
    if body.color is not None:
        cat.color = body.color
    if body.icono is not None:
        cat.icono = body.icono
    await session.commit()
    total = (
        await session.execute(
            select(func.count()).select_from(DocumentCategory).where(
                DocumentCategory.c.category_id == cat.id
            )
        )
    ).scalar()
    out = CategoryOut.model_validate(cat)
    out.total = total or 0
    return out


@router.delete("/{cat_id}", status_code=204)
async def delete_category(cat_id: str, session: AsyncSession = Depends(get_session)):
    cat = await session.get(Category, _uuid(cat_id))
    if cat is None:
        raise HTTPException(404, "categoría no existe")
    if cat.es_sistema:
        raise HTTPException(400, "las categorías de sistema no se pueden eliminar")
    # los documentos NO se borran: solo pierden la etiqueta (RF-CAT-03)
    await session.execute(
        delete(DocumentCategory).where(DocumentCategory.c.category_id == cat.id)
    )
    await session.delete(cat)
    await session.commit()
