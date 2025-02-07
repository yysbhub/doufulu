DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS inbound;
DROP TABLE IF EXISTS outbound;
DROP TABLE IF EXISTS locations;

CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT NOT NULL,
    item_name TEXT NOT NULL,
    item_spec TEXT
);

CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_number INTEGER NOT NULL,
    shelf_number TEXT NOT NULL,
    layer_number INTEGER NOT NULL,
    UNIQUE (warehouse_number, shelf_number, layer_number)
);

CREATE TABLE inbound (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    inbound_qty INTEGER NOT NULL,
    inbound_date DATE NOT NULL,
    location_id INTEGER NOT NULL,
    sn_code TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

CREATE TABLE outbound (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    outbound_qty INTEGER NOT NULL,
    outbound_person TEXT NOT NULL,
    outbound_purpose TEXT NOT NULL,
    outbound_date DATE NOT NULL,
    location_id INTEGER NOT NULL,
    sn_code TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);