import os
import tempfile
import datetime
import subprocess
import json
import wave
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

# OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

VECTOR_STORE_ID = os.environ.get("VECTOR_STORE_ID", "vs_69a34ceb4f488191b243f5a8c56924d9")

# Memoria temporal para UX (luego esto se conecta a DB/vector store)
NOTES: List[Dict[str, Any]] = []


# -----------------------------
# Helpers
# -----------------------------
def utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def try_duration_ms_ffprobe(path: str) -> Optional[int]:
    """
    Try to get duration using ffprobe if available.
    Returns duration in ms or None if ffprobe not available/failed.
    """
    try:
        # ffprobe -v error -show_entries format=duration -of json <file>
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            return None
        data = json.loads(p.stdout)
        dur = data.get("format", {}).get("duration", None)
        if dur is None:
            return None
        # duration is seconds (float)
        ms = int(float(dur) * 1000)
        return ms
    except Exception:
        return None


def try_duration_ms_wav(path: str) -> Optional[int]:
    """
    Calculate WAV duration using wave module.
    Works only if file is valid WAV.
    """
    try:
        with wave.open(path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return None
            seconds = frames / float(rate)
            return int(seconds * 1000)
    except Exception:
        return None


def get_audio_duration_ms(path: str) -> Optional[int]:
    """
    Best-effort duration detection.
    1) ffprobe if available
    2) WAV parsing fallback
    """
    ms = try_duration_ms_ffprobe(path)
    if ms is not None:
        return ms
    # fallback: wav only
    return try_duration_ms_wav(path)


def fmt_duration(ms: Optional[int]) -> str:
    if ms is None:
        return "—"
    sec = ms // 1000
    m = sec // 60
    s = sec % 60
    return f"{m:02d}:{s:02d}"


# -----------------------------
# Models
# -----------------------------
class AskRequest(BaseModel):
    question: str


class VoiceNoteResponse(BaseModel):
    ok: bool
    note_id: int
    created_at: str
    duration_ms: Optional[int]
    transcript: str


# -----------------------------
# API
# -----------------------------
@app.get("/")
def root():
    return {"status": "ok", "service": "brainnotes-cloud"}


@app.post("/ask")
def ask(req: AskRequest):
    # Búsqueda semántica en tu vector store + respuesta
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"Usa las notas como fuente. Responde claro y directo.\n\nPregunta: {req.question}",
        tools=[{
            "type": "file_search",
            "vector_store_ids": [VECTOR_STORE_ID]
        }]
    )

    out_text = ""
    if response.output and len(response.output) > 0:
        for item in response.output:
            if hasattr(item, "content") and item.content:
                for c in item.content:
                    if getattr(c, "type", None) == "output_text":
                        out_text += c.text

    return {"answer": out_text.strip() or "(sin respuesta)"}


@app.post("/voice", response_model=VoiceNoteResponse)
async def voice(file: UploadFile = File(...)):
    """
    Recibe audio (webm/m4a/mp3/wav), lo transcribe y lo guarda en memoria temporal.
    """
    created_at = utc_now_iso()

    suffix = os.path.splitext(file.filename or "")[1] or ".audio"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    # duration
    duration_ms = get_audio_duration_ms(tmp_path)

    # transcription (Whisper / GPT-4o-mini-transcribe depending on your account)
    # We'll try with 'gpt-4o-mini-transcribe' first; if it fails, switch model.
    transcript = ""
    try:
        t = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=open(tmp_path, "rb"),
        )
        transcript = (t.text or "").strip()
    except Exception:
        # fallback (older whisper model)
        try:
            t = client.audio.transcriptions.create(
                model="whisper-1",
                file=open(tmp_path, "rb"),
            )
            transcript = (t.text or "").strip()
        except Exception:
            transcript = ""

    # Save in memory
    note_id = len(NOTES) + 1
    NOTES.append({
        "id": note_id,
        "created_at": created_at,
        "duration_ms": duration_ms,
        "transcript": transcript,
    })

    # cleanup temp file
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return VoiceNoteResponse(
        ok=True,
        note_id=note_id,
        created_at=created_at,
        duration_ms=duration_ms,
        transcript=transcript
    )


@app.get("/notes")
def list_notes(limit: int = 20):
    """
    Lista notas guardadas (memoria temporal).
    """
    return {"notes": list(reversed(NOTES))[: max(1, min(limit, 200))]}


# -----------------------------
# Simple UI (mobile/watch friendly)
# -----------------------------
@app.get("/ui", response_class=HTMLResponse)
def ui():
    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>BrainNotes Voice</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 18px; }}
    h1 {{ margin: 0 0 10px 0; }}
    button {{ padding: 10px 12px; margin-right: 8px; font-size: 16px; }}
    .status {{ margin-top: 10px; font-size: 16px; }}
    textarea {{ width: 100%; height: 130px; font-size: 16px; margin-top: 10px; }}
    .box {{ border: 1px solid #ddd; padding: 10px; border-radius: 10px; margin-top: 12px; }}
    .meta {{ color: #444; font-size: 14px; margin-top: 6px; }}
    .row {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    input {{ width: 100%; padding: 10px; font-size: 16px; }}
    .notes {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>BrainNotes Voice</h1>

  <div class="row">
    <button id="btnRec">🎙 Grabar</button>
    <button id="btnStop" disabled>⏹ Detener</button>
  </div>

  <div class="status" id="status">Listo.</div>
  <div class="meta" id="meta"></div>

  <div class="box">
    <b>Transcripción</b>
    <textarea id="transcript" placeholder="Aquí aparecerá la transcripción..."></textarea>
  </div>

  <div class="box">
    <b>Preguntar a tus notas</b>
    <input id="q" placeholder="Ej: ¿Qué acabo de grabar?"/>
    <button id="btnAsk">Preguntar</button>
    <textarea id="answer" placeholder="Respuesta..."></textarea>
  </div>

  <div class="box">
    <b>Últimas notas</b>
    <div class="notes" id="notes">(cargando...)</div>
  </div>

<script>
let mediaRecorder = null;
let chunks = [];
let recStartMs = null;

function setStatus(t) {{
  document.getElementById("status").innerText = t;
}}

function setMeta(t) {{
  document.getElementById("meta").innerText = t;
}}

async function refreshNotes() {{
  try {{
    const r = await fetch("/notes?limit=10");
    const j = await r.json();
    const notes = j.notes || [];
    const lines = notes.map(n => {{
      const dur = n.duration_ms ? Math.round(n.duration_ms/1000) + "s" : "—";
      return `#${{n.id}}  ${{n.created_at}}  dur:${{dur}}\\n${{n.transcript || "(sin transcripción)"}}\\n`;
    }});
    document.getElementById("notes").innerText = lines.join("\\n");
  }} catch(e) {{
    document.getElementById("notes").innerText = "(error cargando notas)";
  }}
}}

async function startRec() {{
  setStatus("Solicitando micrófono...");
  setMeta("");
  document.getElementById("transcript").value = "";
  chunks = [];
  recStartMs = Date.now();

  const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
  mediaRecorder = new MediaRecorder(stream);

  mediaRecorder.ondataavailable = (e) => {{
    if (e.data.size > 0) chunks.push(e.data);
  }};

  mediaRecorder.onstart = () => {{
    setStatus("Grabando...");
    document.getElementById("btnRec").disabled = true;
    document.getElementById("btnStop").disabled = false;
  }};

  mediaRecorder.onstop = async () => {{
    const localDurMs = Date.now() - recStartMs;
    setStatus("Procesando (subiendo + transcribiendo)...");
    setMeta("Duración local: " + Math.round(localDurMs/1000) + "s");

    const blob = new Blob(chunks, {{ type: chunks[0]?.type || "audio/webm" }});
    const fd = new FormData();
    fd.append("file", blob, "note.webm");

    try {{
      const r = await fetch("/voice", {{ method: "POST", body: fd }});
      const j = await r.json();

      const durSrv = j.duration_ms ? Math.round(j.duration_ms/1000) + "s" : "—";
      setStatus("Guardado ✅ (nota #" + j.note_id + ")");
      setMeta("Fecha: " + j.created_at + " | Duración: " + durSrv);

      document.getElementById("transcript").value = j.transcript || "";
      await refreshNotes();
    }} catch(e) {{
      setStatus("Error al guardar/transcribir ❌");
    }}

    document.getElementById("btnRec").disabled = false;
    document.getElementById("btnStop").disabled = true;
  }};

  mediaRecorder.start();
}}

function stopRec() {{
  if (mediaRecorder) {{
    mediaRecorder.stop();
    // stop tracks
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }}
}}

async function ask() {{
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  document.getElementById("answer").value = "Pensando...";
  try {{
    const r = await fetch("/ask", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ question: q }})
    }});
    const j = await r.json();
    document.getElementById("answer").value = j.answer || "(sin respuesta)";
  }} catch(e) {{
    document.getElementById("answer").value = "(error)";
  }}
}}

document.getElementById("btnRec").addEventListener("click", startRec);
document.getElementById("btnStop").addEventListener("click", stopRec);
document.getElementById("btnAsk").addEventListener("click", ask);

refreshNotes();
</script>
</body>
</html>
"""
    return HTMLResponse(content=html)