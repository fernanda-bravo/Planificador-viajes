from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import requests
from bs4 import BeautifulSoup
import os

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

# --- MODELOS DE DATOS ---
class ProposalCreate(BaseModel):
    user_name: str  # ¡Ahora pedimos el nombre, no el ID!
    url: str
    title: str = ""
    image_url: str = ""
    description: str = "" # Nueva variable
    price: float = 0.0
    required_votes: int = 2 # Consenso familiar en 15 votos

class VoteCreate(BaseModel):
    proposal_id: int
    user_name: str  # ¡Aquí también pedimos el nombre!
    vote_type: str

# Función auxiliar para buscar o crear al usuario por su nombre automáticamente
def get_or_create_user(cursor, name: str) -> int:
    name = name.strip().title() # Limpia espacios y pone mayúscula (ej: " fer " -> "Fer")
    cursor.execute("SELECT id FROM users WHERE name = ?", (name,))
    user = cursor.fetchone()
    if user:
        return user[0] # Si existe, devuelve su ID interno
    else:
        cursor.execute("INSERT INTO users (name, avatar_file) VALUES (?, ?)", (name, "default.png"))
        return cursor.lastrowid # Si no existe, lo crea y devuelve el nuevo ID

# Crea la carpeta 'static' automáticamente si no existe
if not os.path.exists("static"):
    os.makedirs("static")

# Monta la carpeta para archivos web
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home():
    return FileResponse("static/index.html")

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

def scrape_link_data(url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        og_title = soup.find("meta", property="og:title")
        title = og_title["content"] if og_title else "Link Propuesto"
            
        og_image = soup.find("meta", property="og:image")
        image_url = og_image["content"] if og_image else ""

        # NUEVO: Buscar la descripción
        og_desc = soup.find("meta", property="og:description")
        description = og_desc["content"] if og_desc else "No hay descripción disponible."
            
        return {"title": title[:60], "image_url": image_url, "description": description}
    except Exception:
        return {"title": "Enlace de viaje", "image_url": "", "description": ""}

@app.post("/proposals")
def create_proposal(prop: ProposalCreate):
    if not prop.title or not prop.image_url:
        scraped_data = scrape_link_data(prop.url)
        prop.title = prop.title or scraped_data["title"]
        prop.image_url = prop.image_url or scraped_data["image_url"]
        prop.description = prop.description or scraped_data["description"] # Guardamos la descripción

    conn = get_db()
    cursor = conn.cursor()
    user_id = get_or_create_user(cursor, prop.user_name)
    
    # Agregamos description a la consulta SQL
    cursor.execute('''
        INSERT INTO proposals (proposed_by_id, title, url, image_url, description, price, required_votes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, prop.title, prop.url, prop.image_url, prop.description, prop.price, prop.required_votes))
    conn.commit()
    prop_id = cursor.lastrowid
    conn.close()
    
    return {"id": prop_id, "title": prop.title}

@app.get("/proposals")
def get_proposals():
    conn = get_db()
    # Ahora le pedimos a SQLite que cuente los votos a favor y en contra al vuelo
    proposals = conn.execute('''
        SELECT p.*, u.name as proposed_by_name,
               (SELECT COUNT(*) FROM votes WHERE proposal_id = p.id AND vote_type = 'stardrop') as yes_votes,
               (SELECT COUNT(*) FROM votes WHERE proposal_id = p.id AND vote_type = 'shipping_bin') as no_votes
        FROM proposals p 
        JOIN users u ON p.proposed_by_id = u.id
    ''').fetchall()
    conn.close()
    return [dict(p) for p in proposals]

# --- ENDPOINT DE VOTACIÓN ---
@app.post("/votes")
def cast_vote(vote: VoteCreate):
    conn = get_db()
    cursor = conn.cursor()
    
    user_id = get_or_create_user(cursor, vote.user_name)

    try:
        cursor.execute(
            "INSERT INTO votes (proposal_id, user_id, vote_type) VALUES (?, ?, ?)",
            (vote.proposal_id, user_id, vote.vote_type)
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="¡Ya votaste por esta opción!")

    # Consultamos cuántos votos se requieren para esta tarjeta
    req_votes = cursor.execute(
        "SELECT required_votes FROM proposals WHERE id = ?",
        (vote.proposal_id,)
    ).fetchone()[0]

    # 1. Si el voto es a favor, revisamos si aprobó
    if vote.vote_type == 'stardrop':
        stardrops = cursor.execute(
            "SELECT COUNT(*) FROM votes WHERE proposal_id = ? AND vote_type = 'stardrop'",
            (vote.proposal_id,)
        ).fetchone()[0]
        
        if stardrops >= req_votes:
            cursor.execute("UPDATE proposals SET status = 'approved' WHERE id = ?", (vote.proposal_id,))
            conn.commit()
            conn.close()
            return {"mensaje": "¡Consenso alcanzado!", "status": "approved"}

    # 2. NUEVO: Si el voto es en contra, revisamos si se descarta
    elif vote.vote_type == 'shipping_bin':
        shipping_bins = cursor.execute(
            "SELECT COUNT(*) FROM votes WHERE proposal_id = ? AND vote_type = 'shipping_bin'",
            (vote.proposal_id,)
        ).fetchone()[0]

        if shipping_bins >= req_votes:
            cursor.execute("UPDATE proposals SET status = 'rejected' WHERE id = ?", (vote.proposal_id,))
            conn.commit()
            conn.close()
            return {"mensaje": "Idea descartada por el grupo", "status": "rejected"}

    conn.commit()
    conn.close()
    return {"mensaje": "Voto registrado", "status": "pending"}

# --- ENDPOINT PARA BORRAR PROPUESTAS ---
@app.delete("/proposals/{proposal_id}")
def delete_proposal(proposal_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Borramos los votos asociados a esta propuesta primero
    cursor.execute("DELETE FROM votes WHERE proposal_id = ?", (proposal_id,))
    # 2. Borramos la propuesta
    cursor.execute("DELETE FROM proposals WHERE id = ?", (proposal_id,))
    
    conn.commit()
    conn.close()
    return {"mensaje": "¡Propuesta eliminada! 🗑️"}