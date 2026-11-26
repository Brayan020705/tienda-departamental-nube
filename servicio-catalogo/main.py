import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import ObjectId
import redis

app = FastAPI(
    title="Servicio de Catálogo - NovaStore",
    description="Microservicio de productos y reseñas con MongoDB y Cache-Aside en Redis",
    version="1.0.0"
)

# --- Conexión a MongoDB ---
MONGO_USER = os.getenv("MONGO_INITDB_ROOT_USERNAME", "admin_mongo")
MONGO_PASS = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "TiendaMongo2026")
MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASS}@db_mongo:27017/?authSource=admin"

mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
db = mongo_client["tienda_catalogo"]
col_productos = db["productos"]
col_resenas = db["resenas"]

# --- Conexión a Redis (Caché) ---
redis_client = redis.Redis(host="db_redis", port=6379, decode_responses=True, socket_timeout=1.5)

# --- Modelos de entrada ---
class ProductoUpdate(BaseModel):
    nombre: Optional[str] = None
    precio: Optional[float] = Field(None, ge=0)
    especificaciones: Optional[Dict[str, Any]] = None

class ResenaCreate(BaseModel):
    cliente_id: str = Field(..., min_length=2)
    calificacion: int = Field(..., ge=1, le=5)
    comentario: str = Field(..., min_length=3)

def serializar_producto(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc

# --- 1. Health Check ---
@app.get("/health", tags=["Monitoreo"])
def health_check():
    estado = {"servicio": "catalogo", "mongodb": "ok", "redis_cache": "ok"}
    try:
        mongo_client.admin.command("ping")
    except Exception as e:
        estado["mongodb"] = f"error: {str(e)}"
        raise HTTPException(status_code=503, detail=estado)
    try:
        redis_client.ping()
    except Exception:
        estado["redis_cache"] = "degradado (sin caché)"
    return estado

# --- 2. Listar catálogo y filtrar por categoría y precio (con Cache-Aside) ---
@app.get("/productos", tags=["Productos"])
def listar_productos(
    categoria: Optional[str] = Query(None, description="Ej: Electronica, Ropa, Linea Blanca"),
    precio_max: Optional[float] = Query(None, ge=0, description="Precio máximo")
):
    cache_key = f"cache:catalogo:{categoria or 'todas'}:{precio_max or 'sin_limite'}"

    # Intentar leer de Redis primero (tolerante a fallos si Redis está apagado)
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return {"fuente": "redis_cache", "datos": json.loads(cached)}
    except redis.RedisError:
        pass

    filtro = {}
    if categoria:
        filtro["categoria"] = categoria
    if precio_max is not None:
        filtro["precio"] = {"$lte": precio_max}

    try:
        productos = [serializar_producto(p) for p in col_productos.find(filtro)]
    except PyMongoError as e:
        raise HTTPException(status_code=503, detail=f"Error consultando MongoDB: {str(e)}")

    # Guardar en Redis con TTL de 120 segundos
    try:
        redis_client.setex(cache_key, 120, json.dumps(productos))
    except redis.RedisError:
        pass

    return {"fuente": "mongodb", "datos": productos}

# --- 3. Consultar detalle de un producto (con Cache-Aside TTL 300s) ---
@app.get("/productos/{producto_id}", tags=["Productos"])
def obtener_producto(producto_id: str):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID de producto inválido")

    cache_key = f"cache:producto:{producto_id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return {"fuente": "redis_cache", "producto": json.loads(cached)}
    except redis.RedisError:
        pass

    try:
        prod = col_productos.find_one({"_id": ObjectId(producto_id)})
    except PyMongoError as e:
        raise HTTPException(status_code=503, detail=f"Error en MongoDB: {str(e)}")

    if not prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    prod_serializado = serializar_producto(prod)
    try:
        redis_client.setex(cache_key, 300, json.dumps(prod_serializado))
    except redis.RedisError:
        pass

    return {"fuente": "mongodb", "producto": prod_serializado}

# --- 4. Actualizar producto e invalidar caché ---
@app.put("/productos/{producto_id}", tags=["Productos"])
def actualizar_producto(producto_id: str, datos: ProductoUpdate):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID de producto inválido")

    cambios = {k: v for k, v in datos.model_dump().items() if v is not None}
    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    res = col_productos.update_one({"_id": ObjectId(producto_id)}, {"$set": cambios})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Invalidación de caché en Redis
    try:
        redis_client.delete(f"cache:producto:{producto_id}")
        for key in redis_client.scan_iter("cache:catalogo:*"):
            redis_client.delete(key)
    except redis.RedisError:
        pass

    return {"mensaje": "Producto actualizado y caché invalidada", "producto_id": producto_id}

# --- 5. Registrar y consultar reseñas ---
@app.post("/productos/{producto_id}/resenas", status_code=201, tags=["Reseñas"])
def crear_resena(producto_id: str, resena: ResenaCreate):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID de producto inválido")

    if not col_productos.find_one({"_id": ObjectId(producto_id)}):
        raise HTTPException(status_code=404, detail="El producto no existe")

    doc = {
        "producto_id": producto_id,
        "cliente_id": resena.cliente_id,
        "calificacion": resena.calificacion,
        "comentario": resena.comentario,
        "fecha": datetime.now(timezone.utc).isoformat()
    }
    try:
        insertado = col_resenas.insert_one(doc)
        doc["_id"] = str(insertado.inserted_id)
        return {"mensaje": "Reseña registrada", "resena": doc}
    except PyMongoError as e:
        raise HTTPException(status_code=400, detail=f"Validación $jsonSchema falló: {str(e)}")

@app.get("/productos/{producto_id}/resenas", tags=["Reseñas"])
def listar_resenas(producto_id: str):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID de producto inválido")

    resenas = []
    for r in col_resenas.find({"producto_id": producto_id}):
        r["_id"] = str(r["_id"])
        resenas.append(r)
    return {"producto_id": producto_id, "total": len(resenas), "resenas": resenas}