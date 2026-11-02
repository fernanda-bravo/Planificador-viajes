from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import re
import urllib.parse
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
    user_name: str 
    category: str 
    url: str
    title: str = ""
    image_url: str = ""
    description: str = "" # Nueva variable
    price: float = 0.0
    required_votes: int = 2 # Consenso familiar en 15 votos
    lat: float | None = None  # Puede estar vacío si no es un mapa
    lon: float | None = None
    location_name: str = ""

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

def obtener_foto_rapidapi(nombre_lugar: str):
    url = "https://local-business-data.p.rapidapi.com/search" 
    querystring = {"query": nombre_lugar, "language": "es", "region": "cl"} 
    
    headers = {
        "X-RapidAPI-Key": "bb98f7bdc3msh98b4841439bb8a6p16e247jsna6107a6b9ba1", # <- ¡Tu clave real!
        "X-RapidAPI-Host": "local-business-data.p.rapidapi.com"
    }
    
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=5)
        data = response.json()
        
        if "data" in data and len(data["data"]) > 0:
            primer_resultado = data["data"][0]
            urls_extraidas = []
            
            # Entramos directo a la caja que ya sabemos que funciona
            if "photos_sample" in primer_resultado:
                for item in primer_resultado["photos_sample"]:
                    # Revisamos cada diccionario dentro de la lista
                    if isinstance(item, dict):
                        for valor in item.values():
                            if isinstance(valor, str) and valor.startswith("http"):
                                urls_extraidas.append(valor)
                                break # Solo sacamos un link por foto para no repetir
            
            if urls_extraidas:
                print(f"📸 ¡{len(urls_extraidas)} fotos atrapadas!")
                # Unimos un máximo de 4 fotos separadas por el símbolo |
                return "|".join(urls_extraidas[:4])

        return ""
        
    except Exception as e:
        print(f"Error conectando con RapidAPI: {e}")
        return ""
        
    except Exception as e:
        print(f"Error conectando con RapidAPI: {e}")
        return ""

def scrape_link_data(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # --- NUEVA EXTRACCIÓN DE NOMBRE INFALIBLE ---
        nombre_lugar = ""
        
        # Estrategia 1: Robar el nombre directo del link expandido (ej: /place/Hotel+Algarrobo/)
        import urllib.parse
        match_nombre = re.search(r'/place/([^/]+)/', response.url)
        if match_nombre:
            nombre_lugar = urllib.parse.unquote(match_nombre.group(1).replace('+', ' '))
            
        # Estrategia 2: Respaldo por si falla el link
        if not nombre_lugar:
            og_title = soup.find("meta", property="og:title")
            title_html = og_title["content"] if og_title else soup.title.string if soup.title else ""
            nombre_lugar = title_html.replace(" - Google Maps", "").replace("Google Maps", "").strip()

        print(f"🔎 Nombre extraído para buscar foto: '{nombre_lugar}'")

        # --- PEDIR LA FOTO A LA API ---
        image_url = ""
        if nombre_lugar and nombre_lugar.lower() != "lugar en maps":
            image_url = obtener_foto_rapidapi(nombre_lugar)
            
        # EL ARREGLO: Solo usamos la imagen fea del mapa si RapidAPI no encontró nada
        if not image_url:
            print("⚠️ RapidAPI no trajo foto, usando la del mapa por defecto.")
            og_image = soup.find("meta", property="og:image")
            image_url = og_image["content"] if og_image else ""
        
        # 2. Buscar descripción
        og_desc = soup.find("meta", property="og:description")
        description = og_desc["content"] if og_desc else "Ver detalles en el enlace."
        
        lat, lon = None, None
        
        # --- LA MAGIA DE LAS COORDENADAS ---
        match_exacto = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', response.url) or re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
        match_maps = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', response.url) or re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        
        if match_exacto:
            lat = float(match_exacto.group(1))
            lon = float(match_exacto.group(2))
        elif match_maps:
            lat = float(match_maps.group(1))
            lon = float(match_maps.group(2))
                
        # Usamos el nombre real para el título de la tarjeta
        titulo_final = nombre_lugar[:60] if nombre_lugar else "Lugar en Maps"
        
        return {"title": titulo_final, "image_url": image_url, "description": description, "lat": lat, "lon": lon}
    except Exception as e:
        print(f"Error de scraping general: {e}")
        return {"title": "Enlace de viaje", "image_url": "", "description": "", "lat": None, "lon": None}

@app.post("/proposals")
def create_proposal(prop: ProposalCreate):
    if not prop.title or not prop.image_url:
        scraped_data = scrape_link_data(prop.url)
        prop.title = prop.title or scraped_data["title"]
        prop.image_url = prop.image_url or scraped_data["image_url"]
        prop.description = prop.description or scraped_data["description"]
        prop.lat = prop.lat or scraped_data.get("lat")
        prop.lon = prop.lon or scraped_data.get("lon")

   

    conn = get_db()
    cursor = conn.cursor()
    user_id = get_or_create_user(cursor, prop.user_name)
    
    cursor.execute('''
        INSERT INTO proposals (proposed_by_id, category, title, url, image_url, description, price, required_votes, lat, lon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, prop.category, prop.title, prop.url, prop.image_url, prop.description, prop.price, prop.required_votes, prop.lat, prop.lon))
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