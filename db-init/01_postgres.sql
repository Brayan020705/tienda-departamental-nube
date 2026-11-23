CREATE TABLE inventario (
    producto_id VARCHAR(24) PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    nombre_producto VARCHAR(150) NOT NULL,
    precio_unitario NUMERIC(10, 2) NOT NULL CHECK (precio_unitario >= 0),
    stock INT NOT NULL CHECK (stock >= 0),
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ordenes (
    orden_id SERIAL PRIMARY KEY,
    cliente_id VARCHAR(50) NOT NULL,
    total NUMERIC(12, 2) NOT NULL CHECK (total >= 0),
    estado VARCHAR(20) NOT NULL DEFAULT 'COMPLETADA',
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orden_detalles (
    detalle_id SERIAL PRIMARY KEY,
    orden_id INT NOT NULL REFERENCES ordenes(orden_id) ON DELETE CASCADE,
    producto_id VARCHAR(24) NOT NULL REFERENCES inventario(producto_id),
    cantidad INT NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(10, 2) NOT NULL CHECK (precio_unitario >= 0),
    subtotal NUMERIC(12, 2) NOT NULL CHECK (subtotal >= 0)
);

CREATE INDEX idx_ordenes_cliente ON ordenes(cliente_id);

INSERT INTO inventario (producto_id, sku, nombre_producto, precio_unitario, stock) VALUES
('6740a1b2c3d4e5f6a7b8c9d1', 'REF-SAM-001', 'Refrigerador Samsung Top Mount 14 pies', 12499.00, 10),
('6740a1b2c3d4e5f6a7b8c9d2', 'CAM-LEV-042', 'Camisa Casual Oxford Manga Larga', 899.00, 25),
('6740a1b2c3d4e5f6a7b8c9d3', 'LAP-ASU-009', 'Laptop ASUS TUF Gaming F15', 18500.00, 1);