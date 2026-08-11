"""
Interpreta lenguaje natural del técnico y lo convierte en una intención estructurada.

Regla de negocio del PRD (sección 15): la IA no debe modificar datos críticos sin
confirmación cuando haya ambigüedad. Por eso el modelo siempre debe regresar un
campo `confianza` y, si es "baja", el bot debe preguntar antes de actuar
(ver main.py: solo se ejecuta la acción si confianza == "alta").
"""
import json
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = """Eres un intérprete de comandos para un bot de WhatsApp que usan
técnicos de TI para registrar su trabajo. Dado un mensaje, responde ÚNICAMENTE un
JSON (sin texto adicional, sin markdown) con esta forma exacta:

{
  "intencion": "nueva_actividad" | "pausar" | "reanudar" | "finalizar" | "consultar" | "desconocido",
  "ticket": string o null,
  "problema": string o null,
  "solucion": string o null,
  "receptor": string o null,
  "confianza": "alta" | "baja"
}

Ejemplos de mapeo:
- "ya terminé" / "listo, quedó resuelto" -> intencion: finalizar
- "voy a atender otra falla" / "nueva actividad" -> intencion: nueva_actividad
- "ya regresé" / "sigo con lo de antes" -> intencion: reanudar
- "me tengo que ir a otra cosa" / "pausa" -> intencion: pausar
- "qué tengo pendiente" / "mis actividades" -> intencion: consultar

Si el mensaje es ambiguo (p. ej. no queda claro si se refiere a finalizar o pausar),
usa confianza "baja" y elige tu mejor interpretación de todos modos — el bot
confirmará con el técnico antes de ejecutar nada.
"""


def interpretar_mensaje(texto: str) -> dict:
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": texto},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return {
            "intencion": "desconocido", "ticket": None, "problema": None,
            "solucion": None, "receptor": None, "confianza": "baja",
        }

