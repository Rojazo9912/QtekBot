"""
Módulo para aplicar marcas de agua automáticas en fotografías de evidencia.
Incrusta información de auditoría (Ticket, Técnico, Zona, Fecha y Hora)
en una franja semitransparente en la parte inferior de la imagen.
"""
import io
import datetime as dt
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import ZONA_HORARIA


def aplicar_marca_de_agua(
    contenido_imagen: bytes,
    ticket: Optional[str] = None,
    tecnico: Optional[str] = None,
    zona: Optional[str] = None,
    fecha_hora: Optional[dt.datetime] = None,
) -> bytes:
    """Aplica una marca de agua en la imagen con los datos del reporte.
    Si ocurre cualquier error durante el procesamiento, devuelve el contenido original.
    """
    if not contenido_imagen:
        return contenido_imagen

    try:
        # Abrir y corregir orientación EXIF automática de cámaras de celular
        img_original = Image.open(io.BytesIO(contenido_imagen))
        img = ImageOps.exif_transpose(img_original)
        img = img.convert("RGBA")

        ancho, alto = img.size
        if ancho < 100 or alto < 100:
            return contenido_imagen

        # Preparar texto de la marca de agua
        if fecha_hora is None:
            fecha_hora = dt.datetime.now(ZONA_HORARIA)
        fecha_str = fecha_hora.strftime("%Y-%m-%d %H:%M:%S")

        partes = []
        if ticket:
            partes.append(f"Ticket: {ticket.strip()}")
        if zona:
            partes.append(f"Zona: {zona.strip()}")
        if tecnico:
            partes.append(f"Técnico: {tecnico.strip()}")
        partes.append(fecha_str)

        texto_marca = "  |  ".join(partes)

        # Escalar tamaño de fuente proporcionalmente al ancho de la imagen
        tamano_fuente = max(14, int(ancho * 0.022))
        try:
            fuente = ImageFont.truetype("arial.ttf", tamano_fuente)
        except Exception:
            fuente = ImageFont.load_default()

        # Calcular dimensiones de la barra de fondo
        alto_barra = int(tamano_fuente * 2.2)
        y_barra = alto - alto_barra

        # Crear capa de dibujo para la transparencia
        capa_overlay = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(capa_overlay)

        # Rectángulo negro semitransparente en la base
        draw_overlay.rectangle([(0, y_barra), (ancho, alto)], fill=(0, 0, 0, 160))

        # Dibujar texto en blanco centrado verticalmente en la barra
        y_texto = y_barra + int((alto_barra - tamano_fuente) / 2) - 2
        x_texto = max(15, int(ancho * 0.02))
        draw_overlay.text((x_texto, y_texto), texto_marca, font=fuente, fill=(255, 255, 255, 235))

        # Combinar capas
        img_final = Image.alpha_composite(img, capa_overlay).convert("RGB")

        salida = io.BytesIO()
        img_final.save(salida, format="JPEG", quality=88, optimize=True)
        return salida.getvalue()

    except Exception as e:
        print(f"[watermark] Advertencia: no se pudo estampar marca de agua: {e}")
        return contenido_imagen
