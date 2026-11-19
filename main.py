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
import hashlib
import secrets

# Inicializamos la app
app = FastAPI(title="Planificador de Viajes API")

# Función auxiliar para conectarnos a la base de datos
def get_db():
    conn = sqlite3.connect("planificador.db")
    conn.row_factory = sqlite3.Row  # Esto permite leer los resultados como diccionarios
    return conn

# --- FUNCIONES DE CONTRASEÑA ---
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${hashed}"

def verify_password(password: str, stored_hash: str) -> bool:
    salt, hashed = stored_hash.split('$')
    check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000).hex()
    return secrets.compare_digest(check, hashed)

# --- MODELOS ACTUALIZADOS ---
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    avatar_file: str = "default.png"

class UserLogin(BaseModel):
    email: str
    password: str

class TripSettingsUpdate(BaseModel):
    num_travelers: int
    start_date: str = ""
    end_date: str = ""

class ScheduleUpdate(BaseModel):
    planned_day: str = ""
    time_slot: str = ""

class ProposalCreate(BaseModel):
    user_id: int  # Ahora usamos el ID del usuario logueado
    category: str 
    url: str
    title: str = ""
    image_url: str = ""
    description: str = ""
    price: float = 0.0
    lat: float | None = None
    lon: float | None = None
    location_name: str = ""

class VoteCreate(BaseModel):
    proposal_id: int
    user_id: int  # Usamos el ID del usuario logueado
    vote_type: str

@app.post("/register")
def register(user: UserRegister):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, avatar_file) VALUES (?, ?, ?, ?)",
            (user.name.strip(), user.email.strip().lower(), hash_password(user.password), user.avatar_file)
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Ese correo ya está registrado.")
    conn.close()
    return {"id": user_id, "name": user.name.strip(), "email": user.email.strip().lower()}

@app.post("/login")
def login(credentials: UserLogin):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (credentials.email.strip().lower(),)
    ).fetchone()
    conn.close()

    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    return {"id": user["id"], "name": user["name"], "email": user["email"], "avatar_file": user["avatar_file"]}

# --- CONFIGURACIÓN DE VIAJEROS ---
@app.get("/settings")
def get_settings():
    conn = get_db()
    row = conn.execute("SELECT num_travelers, start_date, end_date FROM trip_settings WHERE id = 1").fetchone()
    conn.close()
    num = row["num_travelers"] if row else 2
    return {
        "num_travelers": num,
        "required_votes": (num // 2) + 1,
        "start_date": row["start_date"] if row else "",
        "end_date": row["end_date"] if row else ""
    }

@app.put("/settings")
def update_settings(settings: TripSettingsUpdate):
    if settings.num_travelers < 1:
        raise HTTPException(status_code=400, detail="Debe haber al menos 1 viajero.")
    conn = get_db()
    conn.execute(
        "UPDATE trip_settings SET num_travelers = ?, start_date = ?, end_date = ? WHERE id = 1",
        (settings.num_travelers, settings.start_date, settings.end_date)
    )
    conn.commit()
    conn.close()
    return {
        "num_travelers": settings.num_travelers,
        "required_votes": (settings.num_travelers // 2) + 1,
        "start_date": settings.start_date,
        "end_date": settings.end_date
    }

# --- NUEVO: ASIGNAR DÍA Y HORARIO A UNA PROPUESTA ---
@app.put("/proposals/{proposal_id}/schedule")
def schedule_proposal(proposal_id: int, schedule: ScheduleUpdate):
    conn = get_db()
    conn.execute(
        "UPDATE proposals SET planned_day = ?, time_slot = ? WHERE id = ?",
        (schedule.planned_day, schedule.time_slot, proposal_id)
    )
    conn.commit()
    conn.close()
    return {"mensaje": "¡Itinerario actualizado! 📅"}
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
    conn = get_db()
    cursor = conn.cursor()

    # Verifica que el usuario realmente exista en la base de datos
    user_exists = cursor.execute("SELECT id FROM users WHERE id = ?", (prop.user_id,)).fetchone()
    if not user_exists:
        conn.close()
        raise HTTPException(
            status_code=401,
            detail="No estás registrado. Crea una cuenta o inicia sesión antes de subir un link."
        )

    conn.close()

    # --- A partir de aquí sigue igual (scraping + INSERT) ---
    if not prop.title or not prop.image_url:
        scraped_data = scrape_link_data(prop.url)
        ...

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

    try:
        cursor.execute(
            "INSERT INTO votes (proposal_id, user_id, vote_type) VALUES (?, ?, ?)",
            (vote.proposal_id, vote.user_id, vote.vote_type)
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="¡Ya votaste por esta opción!")

    # Calculamos el quórum dinámicamente según la cantidad actual de viajeros
    num_travelers = cursor.execute("SELECT num_travelers FROM trip_settings WHERE id = 1").fetchone()[0]
    req_votes = (num_travelers // 2) + 1  # Si prefieres unanimidad, cambia esto por: req_votes = num_travelers

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