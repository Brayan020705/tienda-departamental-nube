import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import redis

app = FastAPI(
    title="Servicio de Carrito y Sesiones - NovaStore",
    description="Microservicio clave-valor en Redis para carritos de compra y sesiones con expiración TTL",
    version="1.0.0"
)

redis_client = redis.Redis(host="db_redis", port=6379, decode_responses=True, socket_timeout=1.5)

TTL_CARRITO = 86400  # 24 horas
TTL_SESION = 3600    # 1 hora

class SesionCreate(BaseModel):
    cliente_id: str = Field(..., min_length=2)
    nombre: str = Field(..., min_length=2)

class ItemCarrito(BaseModel):
    producto_id: str = Field(..., min_length=24, max_length=24)
    cantidad: int = Field(..., gt=0)

class CantidadUpdate(BaseModel):
    cantidad: int = Field(..., ge=0, description="Si es 0, elimina el producto del carrito")

# --- 1. Health Check ---
@app.get("/health", tags=["Monitoreo"])
def health_check():
    try:
        redis_client.ping()
        return {"servicio": "carrito", "redis": "ok"}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail={"servicio": "carrito", "redis": f"error: {str(e)}"})

# --- 2. Sesiones de Usuario con TTL ---
@app.post("/sesiones", status_code=201, tags=["Sesiones"])
def crear_sesion(datos: SesionCreate):
    token = str(uuid.uuid4())
    clave = f"sesion:{token}"
    try:
        redis_client.hset(clave, mapping={
            "cliente_id": datos.cliente_id,
            "nombre": datos.nombre
        })
        redis_client.expire(clave, TTL_SESION)
        return {"token": token, "cliente_id": datos.cliente_id, "expira_en_segundos": TTL_SESION}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")

@app.get("/sesiones/{token}", tags=["Sesiones"])
def validar_sesion(token: str):
    clave = f"sesion:{token}"
    try:
        sesion = redis_client.hgetall(clave)
        if not sesion:
            raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
        ttl = redis_client.ttl(clave)
        return {"token": token, "datos": sesion, "ttl_restante": ttl}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")

# --- 3. Gestión de Carrito en Redis ---
@app.get("/carrito/{cliente_id}", tags=["Carrito"])
def ver_carrito(cliente_id: str):
    clave = f"carrito:{cliente_id}"
    try:
        items_raw = redis_client.hgetall(clave)
        items = [{"producto_id": pid, "cantidad": int(cant)} for pid, cant in items_raw.items()]
        ttl = redis_client.ttl(clave)
        return {"cliente_id": cliente_id, "items": items, "ttl_restante": ttl if ttl > 0 else 0}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")

@app.post("/carrito/{cliente_id}/items", status_code=201, tags=["Carrito"])
def agregar_al_carrito(cliente_id: str, item: ItemCarrito):
    clave = f"carrito:{cliente_id}"
    try:
        nueva_cantidad = redis_client.hincrby(clave, item.producto_id, item.cantidad)
        redis_client.expire(clave, TTL_CARRITO)
        return {
            "mensaje": "Producto agregado al carrito",
            "cliente_id": cliente_id,
            "producto_id": item.producto_id,
            "cantidad_actual": nueva_cantidad
        }
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")

@app.put("/carrito/{cliente_id}/items/{producto_id}", tags=["Carrito"])
def modificar_cantidad(cliente_id: str, producto_id: str, datos: CantidadUpdate):
    clave = f"carrito:{cliente_id}"
    try:
        if datos.cantidad == 0:
            redis_client.hdel(clave, producto_id)
            return {"mensaje": "Producto eliminado del carrito"}
        redis_client.hset(clave, producto_id, datos.cantidad)
        redis_client.expire(clave, TTL_CARRITO)
        return {"mensaje": "Cantidad actualizada", "producto_id": producto_id, "cantidad": datos.cantidad}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")

@app.delete("/carrito/{cliente_id}/items/{producto_id}", tags=["Carrito"])
def eliminar_item(cliente_id: str, producto_id: str):
    clave = f"carrito:{cliente_id}"
    try:
        eliminados = redis_client.hdel(clave, producto_id)
        if eliminados == 0:
            raise HTTPException(status_code=404, detail="El producto no estaba en el carrito")
        return {"mensaje": "Producto eliminado del carrito"}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")

@app.delete("/carrito/{cliente_id}", tags=["Carrito"])
def vaciar_carrito(cliente_id: str):
    clave = f"carrito:{cliente_id}"
    try:
        redis_client.delete(clave)
        return {"mensaje": "Carrito vaciado correctamente", "cliente_id": cliente_id}
    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {str(e)}")