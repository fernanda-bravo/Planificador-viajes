import sqlite3

def init_db():
    conn = sqlite3.connect("planificador.db")
    cursor = conn.cursor()

    # 1. Tabla de Usuarios con registro formal
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            avatar_file TEXT DEFAULT 'default.png'
        )
    ''')

    # 2. Configuración del viaje (viajeros + fechas)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trip_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            num_travelers INTEGER NOT NULL DEFAULT 2,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT ''
        )
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO trip_settings (id, num_travelers, start_date, end_date)
        VALUES (1, 2, '', '')
    ''')

    # 3. Tabla de Propuestas (con día y bloque horario)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposed_by_id INTEGER,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            image_url TEXT,
            description TEXT, 
            price REAL,
            status TEXT DEFAULT 'pending',
            lat REAL, 
            lon REAL,
            planned_day TEXT DEFAULT '',
            time_slot TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proposed_by_id) REFERENCES users(id)
        )
    ''')

    # 4. Tabla de Votación (igual que antes)
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

    conn.commit()
    conn.close()
    print("🌱 Base de datos 'planificador.db' inicializada con éxito.")

if __name__ == "__main__":
    init_db()