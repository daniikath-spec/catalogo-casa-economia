# La Casa de la Economía — procesador masivo real (v2)

Aplicación web **independiente de la tienda e inventario**. Selecciona **hasta 800 fotografías en el mismo selector** (400 fotografías del producto + 400 de su código), revisa las parejas y pulsa «Subir y procesar todo». Envía las parejas una a una para no enviar un formulario gigantesco al servidor. El servidor procesa en segundo plano y ofrece **descarga JPG individual por producto y ZIP opcional** con JPG individuales nombrados con el código legible, 800×800, fondo blanco, tamaño entre 60 y 120 KiB; también incluye `reporte.csv` y fotos con lectura ambigua/errónea en `PENDIENTES_REVISION/`.

## Qué cambia con respecto al ZIP anterior
- **No usa Photoroom ni pide su API.** Usa `rembg` + modelo `u2net` para quitar el fondo. El modelo se descarga una vez al comenzar, por lo que la primera ejecución tarda más. Verifica licencia del modelo seleccionado para uso comercial antes de producción.
- Frontend web compatible con selección múltiple; no exige construir ZIP para cargar.
- **No usa Streamlit**: usa FastAPI para subir parejas sucesivas y trabajo en segundo plano. No se recomienda alojamiento gratuito que suspenda la app.
- Códigos se leen con `pyzbar`/libzbar. Si hay varios códigos detectados, queda pendiente (en la foto de prueba IMG_0205 se detectaron dos números distintos).
- Las etiquetas NO son redibujadas con IA; `rembg` extrae los píxeles existentes.

## Cómo fotografiar
1. Selecciona o toma **producto, código, producto, código...** con nombres consecutivos de cámara (IMG_0001, IMG_0002...).
2. Selecciona **todos** los archivos con «Seleccionar ...»; comprueba las parejas mostradas; usa ↔ si se invirtió producto y código en una pareja.
3. Si falta una fotografía entre medio, corrige antes de comenzar. El sistema no puede adivinar una correspondencia faltante.
4. Si un producto tiene **dos códigos distintos** visibles o la foto es ilegible, se guarda para revisión, sin inventar uno.

## Ejecutar en tu computadora (Docker)
1. Instala Docker Desktop. Extrae la carpeta del ZIP.
2. Copia `.env.example` a `.env` y **cambia** `APP_PASSWORD` por una contraseña privada larga.
3. Ejecuta `docker compose up --build -d` en la carpeta que contiene `docker-compose.yml`.
4. Abre `http://localhost:8000` (desde esa computadora). Para acceder desde iPhone/iPad utiliza alojamiento con **HTTPS** (no expongas puerto 8000 sin HTTPS).
5. Conserva los volúmenes `catalogo_data` y `modelos`, el primero guarda lotes/descargas y el segundo el modelo descargado. Haz copia de seguridad de los ZIP antes de cancelar el alojamiento.

## Publicar una web privada
Sube **los archivos de ESTA carpeta**, no el ZIP anterior de Streamlit, al repositorio de GitHub. Despliega como **servicio Docker con disco persistente** (ej. VPS / plataforma que soporte Docker y volúmenes); configura `APP_PASSWORD` como variable secreta, `DATA_DIR=/data` y `U2NET_HOME=/models`; configura HTTPS, almacenamiento persistente para `/data` y `/models`. Puerto de escucha `PORT` o 8000.

Para 400 productos al día, comienza con prueba de 3, luego 10, 25 y 100. Un servidor CPU puede tardar bastante con segmentación; prueba antes de comprometerse con 400 diarios. Recomendable estimar al menos 8 GB RAM y SSD amplio para imágenes originales y resultados, o contratar GPU. Este ejemplo usa **un solo worker**: no escales a varios procesos sin implementar una cola de trabajos compartida y control de concurrencia.

## Seguridad/limitaciones
- No publiques `.env` ni contraseña en GitHub. Repositorio preferentemente privado.
- Los lotes se guardan en disco hasta que los borres manualmente; controla capacidad y borra lotes antiguos **después de descargar y respaldar**.
- La contraseña limita los accesos de la API. Para operación empresarial real agrega tasa de peticiones, monitoreo y backups en la infraestructura.
- El navegador necesita permanecer abierto **durante la subida**; puede cerrarse durante el procesamiento, pero esta primera versión no implementa una interfaz para retomar un lote por ID en otra sesión.
- Algunas fotos con transparencia o empaques brillantes requieren revisión manual. No es garantía de 100% de recortes perfectos.
- JPG mínimo de 60 KiB se consigue con comentario JPEG inocuo si el archivo optimizado ya pesa menos: esto no cambia los píxeles. Se rechazan imágenes que exceden 120 KiB incluso en calidad 18 con submuestreo 4:4:4.
- El ZIP anterior de Photoroom no es la base de esta versión y no se necesita pagar Photoroom Ultra.


## Correcciones de esta revisión (25-09-2026)
- Botón para descargar un JPG por producto, con nombre del código. ZIP queda opcional.
- Botón para ver la foto original de un código que falló, escribir el código correcto y volver a procesar solo ese producto.
- Corregida la numeración de las fotografías pendientes dentro del ZIP.
- **No se ha validado el recorte real de rembg con 800 fotografías ni la calidad comercial de todos los productos.** Las pruebas automatizadas simulan el recorte y no reemplazan una prueba visual sobre originales.
- Un lote de 800 fotos corresponde a **400 productos** porque aquí cada producto usa dos fotografías. No confundir con 800 productos al día.
