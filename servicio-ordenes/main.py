import os
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException

app = FastAPI(
    title="Servicio de Órdenes e Inventario - NovaStore",
    description="Microservicio relacional ACID en PostgreSQL con bloqueo pesimista FOR UPDATE",
    version="1.0.0"
)

PG_HOST = "db_postgres"
PG_DB = os.getenv("POSTGRES_DB", "tienda_ordenes")
PG_USER = os.getenv("POSTGRES_USER", "admin_tienda")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "TiendaPg2026")

URL_CARRITO = "http://api_carrito:8002"
URL_CATALOGO = "http://api_catalogo:8001"

def get_db_connection():
    return psycopg2.connect(
        host=PG_HOST,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASS,
        connect_timeout=3
    )

# --- 1. Health Check ---
@app.get("/health", tags=["Monitoreo"])
def health_check():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.close()
        conn.close()
        return {"servicio": "ordenes", "postgresql": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail={"servicio": "ordenes", "postgresql": f"error: {str(e)}"})

# --- 2. Consultar inventario actual ---
@app.get("/inventario", tags=["Inventario"])
def listar_inventario():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT producto_id, sku, nombre_producto, precio_unitario, stock FROM inventario ORDER BY sku;")
    filas = cur.fetchall()
    cur.close()
    conn.close()
    return {"inventario": filas}

# --- 3. Confirmar Compra (Transacción ACID + API Carrito) ---
@app.post("/ordenes/confirmar/{cliente_id}", status_code=201, tags=["Órdenes"])
def confirmar_compra(cliente_id: str):
    # Paso A: Obtener carrito mediante API del Servicio de Carrito (nunca tocando Redis directo)
    try:
        resp_carrito = httpx.get(f"{URL_CARRITO}/carrito/{cliente_id}", timeout=3.0)
        resp_carrito.raise_for_status()
        items = resp_carrito.json().get("items", [])
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Servicio de Carrito no disponible: {str(e)}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Error al leer el carrito")

    if not items:
        raise HTTPException(status_code=400, detail="El carrito está vacío; no se puede procesar la compra")

    # Paso B: Transacción ACID en PostgreSQL con bloqueo de fila (FOR UPDATE)
    conn = get_db_connection()
    try:
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=RealDictCursor)

        total_orden = 0.0
        detalles_validados = []

        # Ordenar por producto_id evita interbloqueos (deadlocks) entre compras concurrentes
        for item in sorted(items, key=lambda x: x["producto_id"]):
            pid = item["producto_id"]
            cant = item["cantidad"]

            cur.execute(
                "SELECT producto_id, nombre_producto, precio_unitario, stock FROM inventario WHERE producto_id = %s FOR UPDATE;",
                (pid,)
            )
            prod_db = cur.fetchone()

            if not prod_db:
                raise HTTPException(status_code=404, detail=f"Producto {pid} no existe en inventario")

            if prod_db["stock"] < cant:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stock insuficiente para '{prod_db['nombre_producto']}'. Disponible: {prod_db['stock']}, solicitado: {cant}"
                )

            precio = float(prod_db["precio_unitario"])
            subtotal = round(precio * cant, 2)
            total_orden = round(total_orden + subtotal, 2)

            # Descontar inventario
            cur.execute(
                "UPDATE inventario SET stock = stock - %s, actualizado_en = CURRENT_TIMESTAMP WHERE producto_id = %s;",
                (cant, pid)
            )
            detalles_validados.append((pid, cant, precio, subtotal))

        # Crear encabezado de la orden
        cur.execute(
            "INSERT INTO ordenes (cliente_id, total, estado) VALUES (%s, %s, 'COMPLETADA') RETURNING orden_id, creado_en;",
            (cliente_id, total_orden)
        )
        orden_creada = cur.fetchone()
        orden_id = orden_creada["orden_id"]

        # Insertar renglones de la orden
        for pid, cant, precio, subtotal in detalles_validados:
            cur.execute(
                """INSERT INTO orden_detalles (orden_id, producto_id, cantidad, precio_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s);""",
                (orden_id, pid, cant, precio, subtotal)
            )

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error transaccional; compra revertida: {str(e)}")
    finally:
        cur.close()
        conn.close()

    # Paso C: Vaciar carrito vía API del Servicio de Carrito
    carrito_vaciado = True
    try:
        httpx.delete(f"{URL_CARRITO}/carrito/{cliente_id}", timeout=3.0)
    except httpx.RequestError:
        carrito_vaciado = False

    return {
        "mensaje": "Compra confirmada exitosamente",
        "orden_id": orden_id,
        "cliente_id": cliente_id,
        "total": total_orden,
        "carrito_vaciado": carrito_vaciado
    }

# --- 4. Consultar historial de compras de un cliente ---
@app.get("/ordenes/cliente/{cliente_id}", tags=["Órdenes"])
def historial_compras(cliente_id: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT orden_id, total, estado, creado_en FROM ordenes WHERE cliente_id = %s ORDER BY creado_en DESC;",
        (cliente_id,)
    )
    ordenes = cur.fetchall()

    for orden in ordenes:
        cur.execute(
            """SELECT d.producto_id, i.nombre_producto, d.cantidad, d.precio_unitario, d.subtotal
               FROM orden_detalles d
               JOIN inventario i ON d.producto_id = i.producto_id
               WHERE d.orden_id = %s;""",
            (orden["orden_id"],)
        )
        orden["detalles"] = cur.fetchall()

    cur.close()
    conn.close()
    return {"cliente_id": cliente_id, "total_ordenes": len(ordenes), "ordenes": ordenes}