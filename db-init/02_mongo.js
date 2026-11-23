db = db.getSiblingDB('tienda_catalogo');

db.createCollection("productos", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["sku", "nombre", "categoria", "precio", "especificaciones"],
      properties: {
        sku: { bsonType: "string" },
        nombre: { bsonType: "string" },
        categoria: { bsonType: "string" },
        precio: { bsonType: ["double", "int"], minimum: 0 },
        especificaciones: { bsonType: "object" }
      }
    }
  }
});

db.createCollection("resenas", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["producto_id", "cliente_id", "calificacion", "comentario"],
      properties: {
        producto_id: { bsonType: "string" },
        cliente_id: { bsonType: "string" },
        calificacion: { bsonType: "int", minimum: 1, maximum: 5 },
        comentario: { bsonType: "string", minLength: 3 }
      }
    }
  }
});

db.productos.createIndex({ categoria: 1, precio: 1 });
db.resenas.createIndex({ producto_id: 1 });

db.productos.insertMany([
  {
    _id: ObjectId("6740a1b2c3d4e5f6a7b8c9d1"),
    sku: "REF-SAM-001",
    nombre: "Refrigerador Samsung Top Mount 14 pies",
    categoria: "Linea Blanca",
    marca: "Samsung",
    precio: 12499.00,
    especificaciones: { capacidad_pies: 14, voltaje: "110V", color: "Acero Inoxidable" }
  },
  {
    _id: ObjectId("6740a1b2c3d4e5f6a7b8c9d2"),
    sku: "CAM-LEV-042",
    nombre: "Camisa Casual Oxford Manga Larga",
    categoria: "Ropa",
    marca: "Levi's",
    precio: 899.00,
    especificaciones: { talla: "L", material: "100% Algodón", corte: "Slim Fit" }
  },
  {
    _id: ObjectId("6740a1b2c3d4e5f6a7b8c9d3"),
    sku: "LAP-ASU-009",
    nombre: "Laptop ASUS TUF Gaming F15",
    categoria: "Electronica",
    marca: "ASUS",
    precio: 18500.00,
    especificaciones: { ram: "16GB", procesador: "Intel Core i7", almacenamiento: "512GB SSD" }
  }
]);