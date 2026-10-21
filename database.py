import sqlite3

def init_db():
    # Conecta a la base de datos (si no existe, crea el archivo automáticamente)
    conn = sqlite3.connect("planificador.db")
    cursor = conn.cursor()

    # 1. Tabla de Usuarios (Granjeros/Viajeros)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            avatar_file TEXT
        )
    ''')

    # 2. Tabla de Propuestas (Arriendos, Vuelos, Panoramas)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposed_by_id INTEGER,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            image_url TEXT,
            price REAL,
            status TEXT DEFAULT 'pending',
            required_votes INTEGER DEFAULT 4, -- Aquí defines si es el viaje de 4 o 15 personas
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proposed_by_id) REFERENCES users(id)
        )
    ''')

    # 3. Tabla de Votación (Evita votos dobles con UNIQUE)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id INTEGER,
            user_id INTEGER,
            vote_type TEXT NOT NULL,
            voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(proposal_id, user_id),
            FOREIGN KEY (proposal_id) REFERENCES proposals(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Guardar cambios y cerrar
    conn.commit()
    conn.close()
    print("🌱 Base de datos 'planificador.db' inicializada con éxito.")

if __name__ == "__main__":
    init_db()