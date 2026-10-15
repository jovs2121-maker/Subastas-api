import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

SCRAPERAPI_KEY = "06f7f3b916d56c6ba104eb3e627872e9"
SUPABASE_URL = "https://pstlkaownxfinkexkjem.supabase.co"
SUPABASE_KEY = "sb_publishable_bqY5NQAf_hX14scN4GkeUQ_0M6GXr6S"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"status": "API de Subastas Mexicali Activa"}

@app.get("/scrap")
def scrap_lote(lote: str):
    lote_num = str(lote).strip()
    url_target = f"https://bid.cars/en/lot/0-{lote_num}"

    payload = {
        "api_key": SCRAPERAPI_KEY,
        "url": url_target,
        "render": "true"
    }

    try:
        resp = requests.get("https://api.scraperapi.com/", params=payload, timeout=90)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Error de respuesta en ScraperAPI")

        html_text = resp.text
        soup = BeautifulSoup(html_text, "html.parser")

        vehicle_data = {}
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                c = json.loads(s.string)
                if c.get("@type") == "Vehicle":
                    vehicle_data = c
                    break
            except Exception:
                continue

        anio = None
        if "productionDate" in vehicle_data:
            try:
                anio = int(vehicle_data["productionDate"])
            except Exception:
                pass
        if not anio:
            m_a = re.search(r"/(19\d{2}|20\d{2})-", url_target) or re.search(r"\b(19\d{2}|20\d{2})\b", soup.text)
            if m_a:
                anio = int(m_a.group(1))

        marca = vehicle_data.get("manufacturer", "")
        modelo = vehicle_data.get("model", "")
        vin = vehicle_data.get("vehicleIdentificationNumber")
        if not vin:
            m_v = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", url_target) or re.search(r"VIN[:\s\n]+([A-HJ-NPR-Z0-9]{17})", soup.text, re.IGNORECASE)
            if m_v:
                vin = m_v.group(1)

        tipo_dano = vehicle_data.get("knownVehicleDamages")
        if not tipo_dano:
            m_dmg = re.search(r"(?:Primary damage|Damage)[:\s\n]+([A-Za-z\s]+)", soup.text, re.IGNORECASE)
            tipo_dano = m_dmg.group(1).strip().split("\n")[0] if m_dmg else "Desconocido"

        foto_url = vehicle_data.get("image", None)

        patio = "Desconocido"
        m_loc = re.search(r"Location[:\s\n]+([A-Za-z0-9\s,\(\)]+)", soup.text, re.IGNORECASE)
        if m_loc:
            patio = m_loc.group(1).strip().split("\n")[0]

        ventas_sold = []
        origen = "Copart"
        odometro = None

        filas = soup.find_all("tr")
        for f in filas:
            ths = f.find_all("th")
            tds = f.find_all("td")
            if ths and "IAA" in ths[0].get_text(strip=True):
                origen = "IAAI"

            if len(tds) >= 5:
                fecha_str = tds[0].get_text(strip=True)
                precio_str = tds[2].get_text(strip=True)
                odo_str = tds[3].get_text(strip=True)
                status_str = tds[4].get_text(strip=True)

                clean_odo = re.sub(r"[^\d]", "", odo_str)
                if clean_odo and not odometro:
                    odometro = int(clean_odo)

                m_p = re.search(r"\$([\d,]+)", precio_str)
                monto = float(m_p.group(1).replace(",", "")) if m_p else None

                if "sold" in status_str.lower() and "not" not in status_str.lower() and monto:
                    ventas_sold.append({"fecha": fecha_str, "monto": monto})

        oferta_final = None
        resultado = "NOT_SOLD"

        if ventas_sold:
            ventas_sold.sort(key=lambda x: x["fecha"], reverse=True)
            oferta_final = ventas_sold[0]["monto"]
            resultado = "SOLD"

        if not odometro:
            m_odo = re.search(r"(\d{1,3}[\s,]\d{3})\s*mi", soup.text)
            if m_odo:
                odometro = int(re.sub(r"[^\d]", "", m_odo.group(1)))

        registro = {
            "lote": str(lote_num),
            "origen": origen,
            "vin": vin,
            "anio": anio,
            "marca": marca,
            "modelo": modelo,
            "odometro": odometro,
            "tipo_dano": tipo_dano,
            "ubicacion_patio": patio,
            "oferta_final": oferta_final,
            "resultado": resultado,
            "foto_url": foto_url,
            "fecha_subasta": datetime.now(timezone.utc).isoformat()
        }

        supabase.table("lotes").upsert(registro, on_conflict="lote").execute()
        return {"success": True, "data": registro}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
