from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3

# Inicializamos la app
app = FastAPI(title="Planificador de Viajes API")

# Función auxiliar para conectarnos a la base de datos
def get_db():
    conn = sqlite3.connect("planificador.db")
    conn.row_factory = sqlite3.Row  # Esto permite leer los resultados como diccionarios
    return conn

# Definimos cómo deben llegar los datos para crear un usuario (Pydantic)
class UserCreate(BaseModel):
    name: str
    avatar_file: str = "default.png"

class ProposalCreate(BaseModel):
    proposed_by_id: int
    title: str
    url: str
    image_url: str = ""
    price: float = 0.0
    required_votes: int = 4 # Por defecto 4 para L.A., pero puedes mandar 15 para la playa

class VoteCreate(BaseModel):
    proposal_id: int
    user_id: int
    vote_type: str # Aceptará 'stardrop' (sí) o 'shipping_bin' (no)

@app.get("/")
def home():
    return {"mensaje": "¡El servidor está corriendo! 🍄"}

# Endpoint para ver todos los usuarios
@app.get("/users")
def get_users():
    conn = get_db()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return [dict(u) for u in users]

# Endpoint para agregar un nuevo usuario
@app.post("/users")
def create_user(user: UserCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (name, avatar_file) VALUES (?, ?)", (user.name, user.avatar_file))
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return {"id": user_id, "name": user.name, "mensaje": "¡Granjero registrado con éxito!"}

@app.post("/proposals")
def create_proposal(prop: ProposalCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO proposals (proposed_by_id, title, url, image_url, price, required_votes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (prop.proposed_by_id, prop.title, prop.url, prop.image_url, prop.price, prop.required_votes))
    conn.commit()
    prop_id = cursor.lastrowid
    conn.close()
    return {"id": prop_id, "title": prop.title, "mensaje": "¡Propuesta agregada al tablón!"}

@app.get("/proposals")
def get_proposals():
    conn = get_db()
    # Esta consulta une la propuesta con el nombre del usuario que la creó
    proposals = conn.execute('''
        SELECT p.*, u.name as proposed_by_name 
        FROM proposals p 
        JOIN users u ON p.proposed_by_id = u.id
    ''').fetchall()
    conn.close()
    return [dict(p) for p in proposals]

# --- ENDPOINT DE VOTACIÓN (La lógica mágica) ---

@app.post("/votes")
def cast_vote(vote: VoteCreate):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Intentar registrar el voto
    try:
        cursor.execute(
            "INSERT INTO votes (proposal_id, user_id, vote_type) VALUES (?, ?, ?)",
            (vote.proposal_id, vote.user_id, vote.vote_type)
        )
    except sqlite3.IntegrityError:
        # Si salta este error, es porque nuestra regla UNIQUE bloqueó un doble voto
        conn.close()
        raise HTTPException(status_code=400, detail="Este granjero ya votó por esta propuesta")

    # 2. Si el voto es positivo ('stardrop'), revisamos si logramos el consenso
    if vote.vote_type == 'stardrop':
        # Contamos cuántos stardrops tiene esta propuesta
        stardrops = cursor.execute(
            "SELECT COUNT(*) FROM votes WHERE proposal_id = ? AND vote_type = 'stardrop'",
            (vote.proposal_id,)
        ).fetchone()[0]
        
        # Consultamos cuántos votos se requieren
        req_votes = cursor.execute(
            "SELECT required_votes FROM proposals WHERE id = ?",
            (vote.proposal_id,)
        ).fetchone()[0]

        # 3. ¿Llegamos a la meta?
        if stardrops >= req_votes:
            cursor.execute("UPDATE proposals SET status = 'approved' WHERE id = ?", (vote.proposal_id,))
            conn.commit()
            conn.close()
            return {"mensaje": "¡Consenso alcanzado! Lote completado 🌟", "status": "approved"}

    conn.commit()
    conn.close()
    return {"mensaje": "Voto registrado en la Caja de Envíos", "status": "pending"}