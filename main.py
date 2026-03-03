import os
import tempfile

from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from openai import OpenAI

app = FastAPI()

# Cliente OpenAI
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Memoria temporal (solo para pruebas UX)
NOTES = []

# ⚠️ Tu vector store actual
VECTOR_STORE_ID = "vs_69a34ceb4f488191b243f5a8c56924d9"


# ==============================
# MODELOS
# ==============================

class AskRequest(BaseModel):
    question: str


class VoiceNoteResponse(BaseModel):
    ok: bool
    filename: str
    transcript: str
    note_id: int


# ==============================
# ROOT
# ==============================

@app.get("/")
def root():
    return {"status": "ok", "service": "brainnotes-cloud"}


# ==============================
# ASK (consulta a vector store)
# ==============================

@app.post("/ask")
def ask(req: AskRequest):

    # Unir notas de voz recientes
    local_context = ""
    if NOTES:
        for n in NOTES[-10:]:
            local_context += f"- {n['transcript']}\n"

    full_prompt = f"""
Usa las siguientes notas como fuente principal:

{local_context}

Pregunta: {req.question}

Responde claro y directo.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=full_prompt
    )

    out_text = ""

    if response.output:
        for item in response.output:
            if hasattr(item, "content") and item.content:
                for c in item.content:
                    if getattr(c, "type", None) == "output_text":
                        out_text += c.text

    return {"answer": out_text.strip() or "(sin respuesta)"}


# ==============================
# VOICE NOTE (guardar nota de voz)
# ==============================

@app.post("/voice-note", response_model=VoiceNoteResponse)
async def voice_note(file: UploadFile = File(...)):
    # Guardar temporalmente el audio recibido
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    try:
        # Transcribir con OpenAI
        with open(tmp_path, "rb") as f:
            tr = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=f,
            )

        transcript = (tr.text or "").strip()

        # Guardar en memoria temporal
        NOTES.append({
            "type": "voice",
            "filename": file.filename,
            "transcript": transcript
        })

        note_id = len(NOTES) - 1

        return {
            "ok": True,
            "filename": file.filename,
            "transcript": transcript,
            "note_id": note_id
        }

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ==============================
# LISTAR NOTAS (solo UX testing)
# ==============================

@app.get("/notes")
def list_notes():
    return {
        "count": len(NOTES),
        "notes": NOTES
    }


# ==============================
# UI SIMPLE PARA PROBAR DESDE TELÉFONO / RELOJ
# ==============================

UI_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>BrainNotes Voice</title>
</head>
<body style="font-family:system-ui;margin:16px">

<h2>BrainNotes Voice</h2>

<button id="rec">🎙️ Grabar</button>
<button id="stop" disabled>⏹️ Detener</button>
<button id="send" disabled>⬆️ Enviar</button>

<div id="status" style="margin:10px 0;"></div>

<h3>Transcripción</h3>
<textarea id="t" rows="6" style="width:100%;"></textarea>

<script>
let mr, chunks=[], blob;

const rec = document.getElementById("rec");
const stop = document.getElementById("stop");
const send = document.getElementById("send");
const statusEl = document.getElementById("status");
const t = document.getElementById("t");

rec.onclick = async () => {
  chunks = [];
  blob = null;

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mr = new MediaRecorder(stream);

  mr.ondataavailable = e => chunks.push(e.data);
  mr.onstop = () => {
    blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
    send.disabled = false;
    statusEl.innerText = "Listo para enviar.";
  };

  mr.start();
  rec.disabled = true;
  stop.disabled = false;
  statusEl.innerText = "Grabando...";
};

stop.onclick = () => {
  mr.stop();
  stop.disabled = true;
  rec.disabled = false;
  statusEl.innerText = "Procesando...";
};

send.onclick = async () => {
  const fd = new FormData();
  fd.append("file", blob, "note.webm");

  statusEl.innerText = "Enviando...";
  const r = await fetch("/voice-note", {
    method: "POST",
    body: fd
  });

  const j = await r.json();
  t.value = j.transcript || JSON.stringify(j);
  statusEl.innerText = "Guardado ✅";
};
</script>

</body>
</html>
"""

@app.get("/ui", response_class=HTMLResponse)
def ui():
    return UI_HTML