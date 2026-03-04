import os
import tempfile
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI(title="BrainNotes Cloud", version="0.2.0")

# OpenAI client (Render: configura OPENAI_API_KEY en Environment Variables)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Memoria temporal (para UX). Ojo: en Render free puede reiniciarse.
NOTES: List[dict] = []  # {id:int, transcript:str, created_at:str}

class AskRequest(BaseModel):
    question: str

class VoiceNoteResponse(BaseModel):
    ok: bool
    note_id: int
    transcript: str

@app.get("/")
def root():
    return {"status": "ok", "service": "brainnotes-cloud"}

@app.get("/ui")
def ui():
    # UI simple, enfocada en feedback y flujo natural (stop => upload+transcribe)
    html = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>BrainNotes Voice</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 16px; max-width: 680px; }
    h1 { margin: 0 0 12px 0; font-size: 34px; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    button { font-size: 16px; padding: 10px 12px; border-radius: 10px; border: 1px solid #ccc; background: #fff; }
    button.primary { background: #111; color: #fff; border-color: #111; }
    button.danger { background: #b00020; color: #fff; border-color: #b00020; }
    button:disabled { opacity: 0.55; }
    .card { border: 1px solid #e6e6e6; border-radius: 14px; padding: 12px; margin-top: 12px; }
    .status { font-weight: 600; }
    .pill { display:inline-block; padding: 6px 10px; border-radius: 999px; background:#f3f3f3; font-size: 14px; }
    textarea, input { width: 100%; font-size: 16px; padding: 10px; border-radius: 10px; border: 1px solid #ccc; }
    pre { white-space: pre-wrap; word-wrap: break-word; background:#0b0b0b; color:#eaeaea; padding: 12px; border-radius: 12px; }
    .muted { color: #666; font-size: 14px; }
    .list { margin: 10px 0 0; padding: 0 0 0 18px; }
  </style>
</head>
<body>
  <h1>BrainNotes Voice</h1>
  <div class="muted">Flujo natural: <b>Detener</b> ⇒ sube ⇒ transcribe ⇒ guarda (automático).</div>

  <div class="card">
    <div class="row">
      <button id="btnStart" class="primary">🎙 Grabar</button>
      <button id="btnStop" class="danger" disabled>⏹ Detener</button>
      <span id="statusPill" class="pill">Listo</span>
    </div>

    <div style="margin-top:10px">
      <div class="status">Transcripción</div>
      <textarea id="transcript" rows="4" placeholder="Aquí aparecerá la transcripción automáticamente..."></textarea>
      <div class="muted" style="margin-top:6px" id="debug"></div>
    </div>
  </div>

  <div class="card">
    <div class="status">Preguntar a tus notas</div>
    <div class="row" style="margin-top:8px">
      <button id="btnSpeakQ">🗣️ Hablar pregunta</button>
      <button id="btnAsk" class="primary">Preguntar</button>
    </div>
    <div style="margin-top:10px">
      <input id="question" placeholder="Ej: Hazme un resumen de lo que grabé hoy" />
    </div>
    <div style="margin-top:10px">
      <div class="status">Respuesta</div>
      <pre id="answer">(aquí verás la respuesta)</pre>
    </div>
  </div>

  <div class="card">
    <div class="status">Últimas notas</div>
    <ul id="notesList" class="list"></ul>
  </div>

<script>
  const API = location.origin;

  const btnStart = document.getElementById("btnStart");
  const btnStop  = document.getElementById("btnStop");
  const statusPill = document.getElementById("statusPill");
  const transcriptEl = document.getElementById("transcript");
  const debugEl = document.getElementById("debug");

  const btnSpeakQ = document.getElementById("btnSpeakQ");
  const btnAsk = document.getElementById("btnAsk");
  const questionEl = document.getElementById("question");
  const answerEl = document.getElementById("answer");
  const notesList = document.getElementById("notesList");

  let mediaRecorder;
  let chunks = [];

  function setStatus(text) {
    statusPill.textContent = text;
  }

  async function refreshNotes() {
    try {
      const r = await fetch(API + "/notes");
      const data = await r.json();
      notesList.innerHTML = "";
      (data.notes || []).slice(-10).reverse().forEach(n => {
        const li = document.createElement("li");
        li.textContent = `#${n.id}: ${n.transcript}`;
        notesList.appendChild(li);
      });
    } catch (e) {}
  }

  async function uploadAndTranscribe(blob) {
    setStatus("Subiendo…");
    debugEl.textContent = "";
    transcriptEl.value = "";

    const fd = new FormData();
    fd.append("file", blob, "note.webm");

    setStatus("Transcribiendo…");
    const resp = await fetch(API + "/voice-note", { method: "POST", body: fd });
    if (!resp.ok) {
      const err = await resp.text();
      setStatus("Error");
      debugEl.textContent = err;
      return;
    }
    const data = await resp.json();
    transcriptEl.value = data.transcript || "";
    setStatus("Guardado ✅");
    await refreshNotes();
  }

  btnStart.onclick = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };

      mediaRecorder.onstart = () => {
        setStatus("Grabando…");
        btnStart.disabled = true;
        btnStop.disabled = false;
      };

      mediaRecorder.onstop = async () => {
        btnStart.disabled = false;
        btnStop.disabled = true;

        const blob = new Blob(chunks, { type: "audio/webm" });
        // 🔥 UX: STOP = auto enviar + transcribir
        await uploadAndTranscribe(blob);
      };

      mediaRecorder.start();
    } catch (e) {
      setStatus("Error micrófono");
      debugEl.textContent = String(e);
    }
  };

  btnStop.onclick = () => {
    try {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
      }
    } catch (e) {}
  };

  btnAsk.onclick = async () => {
    const q = (questionEl.value || "").trim();
    if (!q) { answerEl.textContent = "Escribe una pregunta primero."; return; }
    answerEl.textContent = "Pensando…";
    const r = await fetch(API + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q })
    });
    const data = await r.json();
    answerEl.textContent = data.answer || "(sin respuesta)";
  };

  // 🗣️ Voz para la pregunta (SpeechRecognition del navegador)
  btnSpeakQ.onclick = async () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      alert("Tu navegador no soporta dictado de voz aquí. Prueba Chrome en Android.");
      return;
    }
    const rec = new SR();
    rec.lang = "es-MX";
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    setStatus("Escuchando pregunta…");
    let finalText = "";

    rec.onresult = (ev) => {
      let t = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        t += ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalText = t;
      }
      questionEl.value = t.trim();
    };

    rec.onerror = (e) => {
      setStatus("Listo");
      debugEl.textContent = "Speech error: " + e.error;
    };

    rec.onend = () => {
      setStatus("Listo");
      if (finalText.trim()) {
        // opcional: auto preguntar al terminar de hablar
        // btnAsk.click();
      }
    };

    rec.start();
  };

  // Al abrir, carga notas
  refreshNotes();
</script>
</body>
</html>
"""
    return HTMLResponse(html)

@app.post("/voice-note", response_model=VoiceNoteResponse)
async def voice_note(file: UploadFile = File(...)):
    # Guardar a archivo temporal
    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    try:
        # Whisper transcription
        # Nota: el SDK acepta file handle
        with open(tmp_path, "rb") as f:
            tr = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=f
            )
        transcript = (getattr(tr, "text", None) or "").strip()

        note_id = len(NOTES) + 1
        NOTES.append({"id": note_id, "transcript": transcript})

        return VoiceNoteResponse(ok=True, note_id=note_id, transcript=transcript)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

@app.get("/notes")
def notes():
    return {"count": len(NOTES), "notes": NOTES}

@app.post("/ask")
def ask(req: AskRequest):
    # UX stage: contestar usando NOTES (sin vector store aún)
    if not NOTES:
        return {"answer": "Aún no tienes notas guardadas. Graba una nota primero."}

    notes_text = "\n".join([f"- ({n['id']}) {n['transcript']}" for n in NOTES[-50:]])

    prompt = f"""
Eres BrainNotes. Responde claro, corto y útil.
Usa SOLO estas notas como fuente.

NOTAS:
{notes_text}

PREGUNTA:
{req.question}
""".strip()

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    out_text = ""
    if resp.output:
        for item in resp.output:
            if hasattr(item, "content") and item.content:
                for c in item.content:
                    if getattr(c, "type", None) == "output_text":
                        out_text += c.text

    return {"answer": out_text.strip() or "(sin respuesta)"}