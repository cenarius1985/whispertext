# Uso local sin autenticación — WISPERTEXT

> **Estado: 📝 borrador**
> WISPERTEXT · Por qué el sistema no tiene login/registro y qué medidas
> de protección aplican igualmente.

## Objetivo

Documentar la decisión "sin login ni registro" (requisito explícito del
usuario) y definir las compensaciones de seguridad para no dejar el sistema
expuesto.

## Alcance

- Exposición de puertos y red.
- Secretos y variables de entorno.
- Contenido y privacidad de los documentos.
- Eliminación de datos.

## Contenido

### 1. Decisión

No hay usuarios, sesiones ni registro. Es una herramienta **personal, de un
solo usuario, en el propio PC** (perfil de uso: escuchar documentos técnicos y
normas). Cualquier petición a la API se considera confiable.

### 2. Compensaciones obligatorias

| Riesgo si no hubiera compensación | Medida |
|---|---|
| Exposición a la red local/Internet | Puertos de `api`, `db`, `redis` y `worker` **no publicados** al host; solo `frontend` (y `nginx` en perfil completo) escuchan, por defecto en `127.0.0.1`. Si se quiere acceso desde otro dispositivo de la LAN, se publica explícitamente a sabiendas. |
| Postgres/Redis sin contraseña accesibles | Viven solo en la red interna del compose; credenciales (aunque sean de desarrollo) viven en `.env` fuera de git. |
| Secretos en el repositorio | `.env.example` solo con defaults sin secretos; `.env` en `.gitignore`. No copiar claves a documentación (regla del vault). |
| Acceso de la API a Bonsai | `BONSAI_BASE_URL` apunta a `host.docker.internal:4687` (servicio local propio); no hay credenciales. Las llamadas son fail-soft. |
| Subida de archivos arbitrarios | Validación server-side: solo tipos permitidos (pdf, md, txt, docx, epub, imágenes de portada), tamaño máximo configurable, nombre saneado, almacenamiento fuera de rutas ejecutables. |
| Path traversal en `/media/**` | Servir solo rutas registradas en la BD (resolución por id/relativa controlada), nunca a partir de input crudo del usuario. |
| CORS | Origen único (frontend); si el frontend se sirve vía nginx mismo origen, CORS cerrado. |
| Pérdida de biblioteca | Runbook de backup pendiente: `pg_dump` + copia del volumen `media/` (ver runbook de backup, pendiente). |

### 3. Eliminación de datos

`DELETE /api/documents/{id}` borra: filas en cascada (párrafos, audios, imágenes,
jobs, exports, progreso) + archivos físicos (MP3, portada, imágenes, PDF
original). Los audios en cache compartidos por hash con **otros** documentos no
se borran (solo su asociación). Confirmación en UI antes de eliminar.

## Ejemplos

`docker compose up -d` en perfil estándar: el único puerto publicado es
`127.0.0.1:3000` (frontend). Desde el navegador local se usa
`http://localhost:3000`; ningún otro equipo de la red puede alcanzar la
plataforma a menos que se edite el compose.

## Checklist de verificación

- [x] Decisión sin auth documentada con compensaciones.
- [x] Puertos/validaciones/path traversal cubiertos como requisitos de implementación.
- [ ] Verificar en código al implementar (ports, CORS, validación de upload).
- [ ] Crear runbook de backup y restauración.
