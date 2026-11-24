import json
import os
import sys
import unicodedata

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()  # lee GEMINI_API_KEY desde el archivo .env
client = genai.Client()
MODELO = "gemini-3.5-flash"  # si da 404, prueba gemini-3.7-flash o gemini-3.8-flash
MAX_VUELTAS = 6

# Inventario (2.1)
if not os.path.exists("inventario.json"):
    with open("inventario.json", "w", encoding="utf-8") as f:
        json.dump({
            "Camisa": {"precio": 45000, "stock": 20},
            "Gorra": {"precio": 30000, "stock": 5},
            "Pantalón": {"precio": 89000, "stock": 12},
            "Medias": {"precio": 8000, "stock": 40},
            "Zapatos": {"precio": 150000, "stock": 3},
        }, f, ensure_ascii=False, indent=2)

with open("inventario.json", encoding="utf-8") as f:
    INVENTARIO = json.load(f)

def normalizar(texto):
    """Minúsculas, sin tildes y sin plural."""
    texto = unicodedata.normalize("NFD", str(texto).lower().strip())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    if texto.endswith("es"):
        return texto[:-2]
    if texto.endswith("s"):
        return texto[:-1]
    return texto

def buscar_producto(nombre):
    """Devuelve el nombre real del producto en el inventario o None."""
    buscado = normalizar(nombre)
    for real in INVENTARIO:
        if normalizar(real) == buscado:
            return real
    return None

def consultar_producto(nombre):
    real = buscar_producto(nombre)
    if real is None:
        return {"existe": False}
    return {"existe": True, "producto": real,
            "precio": INVENTARIO[real]["precio"],
            "stock": INVENTARIO[real]["stock"]}

def calcular_envio(ciudad):
    return 0 if normalizar(ciudad) == "popayan" else 13000

def calcular_descuento(subtotal):
    return round(subtotal * 0.15) if subtotal > 300000 else 0

def calcular_pedido(items, ciudad):
    subtotal = 0
    detalle = []
    for item in items:
        real = buscar_producto(item["producto"])
        if real is None:
            raise ValueError(f"El producto '{item['producto']}' no existe")

        cantidad = item["cantidad"]
        if isinstance(cantidad, float) and cantidad.is_integer():
            cantidad = int(cantidad)  # el modelo a veces manda 2.0
        if not isinstance(cantidad, int) or isinstance(cantidad, bool) or cantidad <= 0:
            raise ValueError("La cantidad debe ser un entero mayor que 0")
        if cantidad > INVENTARIO[real]["stock"]:
            raise ValueError(f"Solo hay {INVENTARIO[real]['stock']} unidades de {real}")

        precio = INVENTARIO[real]["precio"]
        subtotal += precio * cantidad
        detalle.append({"producto": real, "cantidad": cantidad,
                        "precio": precio, "subtotal": precio * cantidad})

    descuento = calcular_descuento(subtotal)
    envio = calcular_envio(ciudad)
    return {"items": detalle, "ciudad": ciudad, "subtotal": subtotal,
            "descuento": descuento, "envio": envio,
            "total": subtotal - descuento + envio}

# Descripción de las herramientas (2.2)
HERRAMIENTAS = [
    {
        "name": "consultar_producto",
        "description": "Consulta si un producto existe y devuelve su precio y su stock. "
                       "Úsala cuando el cliente pregunte por precios o existencias.",
        "parameters": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del producto, por ejemplo 'medias'"},
            },
            "required": ["nombre"],
        },
    },
    {
        "name": "calcular_pedido",
        "description": "Calcula subtotal, descuento, envío y total de un pedido. "
                       "Úsala siempre que haya que dar un total. Necesita la ciudad de envío.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Lista de productos pedidos",
                    "items": {
                        "type": "object",
                        "properties": {
                            "producto": {"type": "string"},
                            "cantidad": {"type": "integer"},
                        },
                        "required": ["producto", "cantidad"],
                    },
                },
                "ciudad": {"type": "string", "description": "Ciudad de envío"},
            },
            "required": ["items", "ciudad"],
        },
    },
]

# Ejecutar lo que pide el modelo (2.3)
FUNCIONES = {
    "consultar_producto": consultar_producto,
    "calcular_pedido": calcular_pedido,
}
def ejecutar_herramienta(nombre, entrada):
    """Devuelve (texto_json, es_error)."""
    if nombre not in FUNCIONES:
        return f"La herramienta '{nombre}' no existe", True
    try:
        resultado = FUNCIONES[nombre](**entrada)
        return json.dumps(resultado, ensure_ascii=False), False
    except (ValueError, KeyError, TypeError) as e:
        return f"Error: {e}", True

# Guardar pedido con confirmación (5.2)
def guardar_pedido(items, ciudad):
    pedido = calcular_pedido(items, ciudad)

    print("\n--- Resumen del pedido ---")
    for i in pedido["items"]:
        print(f"{i['cantidad']} x {i['producto']} = ${i['subtotal']:,}")
    print(f"Subtotal: ${pedido['subtotal']:,}")
    print(f"Descuento: ${pedido['descuento']:,}")
    print(f"Envío ({ciudad}): ${pedido['envio']:,}")
    print(f"TOTAL: ${pedido['total']:,}")

    if input("¿Confirmas el pedido? (s/n): ").strip().lower() != "s":
        return {"guardado": False, "mensaje": "El cliente no confirmó el pedido"}

    pedidos = []
    if os.path.exists("pedidos.json"):
        with open("pedidos.json", encoding="utf-8") as f:
            pedidos = json.load(f)
    pedido["numero"] = len(pedidos) + 1
    pedidos.append(pedido)
    with open("pedidos.json", "w", encoding="utf-8") as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=2)
    return {"guardado": True, "numero": pedido["numero"], "total": pedido["total"]}

def registrar_pedidos():
    """Agrega guardar_pedido a HERRAMIENTAS y FUNCIONES una sola vez."""
    if "guardar_pedido" in FUNCIONES:
        return
    FUNCIONES["guardar_pedido"] = guardar_pedido
    HERRAMIENTAS.append({
        "name": "guardar_pedido",
        "description": "Guarda el pedido del cliente. Pide confirmación al cliente antes de guardar. "
                       "Úsala solo cuando el cliente quiera comprar.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "producto": {"type": "string"},
                            "cantidad": {"type": "integer"},
                        },
                        "required": ["producto", "cantidad"],
                    },
                },
                "ciudad": {"type": "string"},
            },
            "required": ["items", "ciudad"],
        },
    })

# El ciclo del agente (3.1)
SISTEMA = (
    "Eres el asistente de una tienda de ropa. "
    "Usa consultar_producto para precios y stock. "
    "Usa calcular_pedido para todos los totales y envíos; nunca calcules tú. "
    "Si el cliente no menciona la ciudad, pregúntala antes de calcular. "
    "Si un producto no existe o la petición no es correcta, díselo al cliente. "
    "Si piden algo que no tiene que ver con la tienda, responde que solo ayudas con la tienda. "
    "No inventes precios, stock ni productos."
)

def agente(pregunta, historial=None, verbose=False):
    historial = historial or []

    # El historial guarda solo texto: lo convertimos al formato de Gemini
    contenidos = [types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
                  for m in historial]
    contenidos.append(types.Content(role="user", parts=[types.Part(text=pregunta)]))

    config = types.GenerateContentConfig(
        system_instruction=SISTEMA,
        tools=[types.Tool(function_declarations=HERRAMIENTAS)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for vuelta in range(1, MAX_VUELTAS + 1):
        respuesta = client.models.generate_content(
            model=MODELO, contents=contenidos, config=config)
        contenido_modelo = respuesta.candidates[0].content
        llamadas = [p.function_call for p in (contenido_modelo.parts or []) if p.function_call]

        if not llamadas:  # ya no pide herramientas: es la respuesta final
            return respuesta.text or ""

        contenidos.append(contenido_modelo)
        resultados = []
        for llamada in llamadas:
            entrada = dict(llamada.args or {})
            texto, es_error = ejecutar_herramienta(llamada.name, entrada)
            if verbose:
                print(f"[vuelta {vuelta}] {llamada.name}({entrada}) -> {texto}")
            clave = "error" if es_error else "resultado"
            resultados.append(types.Part.from_function_response(
                name=llamada.name, response={clave: texto}))
        contenidos.append(types.Content(role="user", parts=resultados))

    return "Lo siento, no pude completar la solicitud. Intenta de nuevo."

# Pruebas (2.1 y 5.1)
def pruebas():
    print(calcular_pedido([{"producto": "pantalones", "cantidad": 2},
                           {"producto": "zapatos", "cantidad": 1}], "Cali"))
    casos = [
        ("consultar_producto", {"nombre": "pijamas"}),
        ("calcular_pedido", {"items": [{"producto": "gorra", "cantidad": 0}], "ciudad": "Cali"}),
        ("calcular_pedido", {"items": [{"producto": "zapatos", "cantidad": 9}], "ciudad": "Cali"}),
        ("calcular_pedido", {"items": [{"producto": "pijama", "cantidad": 1}], "ciudad": "Cali"}),
        ("herramienta_inventada", {}),
    ]
    for nombre, entrada in casos:
        texto, es_error = ejecutar_herramienta(nombre, entrada)
        print(nombre, "| error:", es_error, "|", texto)
# Chat de consola y reto integrador (4.1)

def chat():
    registrar_pedidos()
    historial = []  # [{"role": "user"/"model", "text": ...}]
    print("Bienvenido a la tienda. Puedes preguntar precios, existencias o hacer un pedido.")
    print("Ejemplo: Quiero 2 camisas, envío a Cali")
    print("Escribe 'salir' para terminar.")

    while True:
        texto = input("\nEscribe tu pregunta o pedido: ").strip()
        if not texto:
            continue
        if texto.lower() == "salir":
            break
        try:
            respuesta = agente(texto, historial[-8:])  # solo los últimos 8 mensajes
        except errors.APIError as e:
            # No se agrega nada al historial para que no quede desordenado
            print(f"Asistente: el servicio falló ({e.code}): {e.message}")
            continue
        print("Asistente:", respuesta)
        historial.append({"role": "user", "text": texto})
        historial.append({"role": "model", "text": respuesta})

    with open("conversacion_tienda.json", "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)
    print("Conversación guardada en conversacion_tienda.json")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pruebas":
        pruebas()
    else:
        chat()