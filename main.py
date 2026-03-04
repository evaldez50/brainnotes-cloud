import os
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

VECTOR_STORE_ID = "vs_69a34ceb4f488191b243f5a8c56924d9"

NOTES = []

class AskRequest(BaseModel):
    question: str


@app.get("/")
def root():
    return {"status": "ok", "service": "brainnotes-cloud"}


@app.post("/ask")
def ask(req: AskRequest):

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"Usa las notas como fuente. Responde claro y directo.\n\nPregunta: {req.question}",
        tools=[{
            "type": "file_search",
            "vector_store_ids": [VECTOR_STORE_ID]
        }]
    )

    out_text = ""

    if response.output:
        for item in response.output:
            if hasattr(item, "content") and item.content:
                for c in item.content:
                    if getattr(c, "type", None) == "output_text":
                        out_text += c.text

    return {"answer": out_text.strip()}


@app.post("/voice")
async def voice(file: UploadFile = File(...)):

    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(await file.read())
        path = tmp.name

    transcript = ""

    try:
        t = client.audio.transcriptions.create(
            model="whisper-1",
            file=open(path, "rb")
        )
        transcript = t.text
    except Exception:
        transcript = ""

    NOTES.append(transcript)

    return {
        "ok": True,
        "transcript": transcript
    }


@app.get("/ui", response_class=HTMLResponse)
def ui():
    return """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>BrainNotes</title>

<style>
body { font-family: Arial; margin:20px }
button { padding:14px; font-size:16px; margin:6px; border-radius:10px }
textarea,input{width:100%;padding:12px;margin-top:10px;font-size:16px}
.hidden{display:none}
</style>

</head>

<body>

<div id="home">
<h1>BrainNotes</h1>

<button onclick="showRecord()">🎙 Grabar</button>
<button onclick="showAsk()">❓ Preguntar</button>
</div>


<div id="record" class="hidden">

<h2>Grabar nota</h2>

<button onclick="startRec()">🎙 Grabar</button>
<button onclick="stopRec()">⏹ Detener</button>

<p id="status"></p>

<textarea id="transcript" placeholder="Aquí aparecerá la transcripción"></textarea>

<button onclick="clearRec()">🧹 Limpiar</button>
<button onclick="back()">⬅ Regresar</button>

</div>


<div id="ask" class="hidden">

<h2>Preguntar</h2>

<button onclick="startQuestion()">🎙 Grabar pregunta</button>
<button onclick="stopQuestion()">⏹ Detener</button>

<input id="question" placeholder="Pregunta...">

<button onclick="ask()">Preguntar</button>

<textarea id="answer" placeholder="Respuesta"></textarea>

<button onclick="speak()">🔊 Reproducir respuesta</button>

<button onclick="clearAsk()">🧹 Limpiar</button>
<button onclick="back()">⬅ Regresar</button>

</div>


<script>

const home=document.getElementById("home")
const record=document.getElementById("record")
const askScreen=document.getElementById("ask")

function showRecord(){
home.classList.add("hidden")
record.classList.remove("hidden")
}

function showAsk(){
home.classList.add("hidden")
askScreen.classList.remove("hidden")
}

function back(){
record.classList.add("hidden")
askScreen.classList.add("hidden")
home.classList.remove("hidden")
}

let mediaRecorder
let chunks=[]

async function startRec(){

const stream=await navigator.mediaDevices.getUserMedia({audio:true})

chunks=[]

mediaRecorder=new MediaRecorder(stream)

mediaRecorder.ondataavailable=e=>chunks.push(e.data)

mediaRecorder.onstart=()=>{
document.getElementById("status").innerText="Grabando..."
}

mediaRecorder.start()

}

async function stopRec(){

mediaRecorder.stop()

mediaRecorder.onstop=async()=>{

document.getElementById("status").innerText="Procesando..."

const blob=new Blob(chunks,{type:"audio/webm"})

const fd=new FormData()

fd.append("file",blob,"note.webm")

const r=await fetch("/voice",{method:"POST",body:fd})

const data=await r.json()

document.getElementById("transcript").value=data.transcript

document.getElementById("status").innerText="Guardado ✅"

}

}

function clearRec(){
document.getElementById("transcript").value=""
document.getElementById("status").innerText=""
}

let recognition

function startQuestion(){

const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition

recognition=new SpeechRecognition()

recognition.lang="es-MX"

recognition.start()

recognition.onresult=e=>{
document.getElementById("question").value=e.results[0][0].transcript
}

}

function stopQuestion(){
if(recognition)recognition.stop()
}

async function ask(){

const q=document.getElementById("question").value

document.getElementById("answer").value="Pensando..."

const r=await fetch("/ask",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({question:q})
})

const data=await r.json()

document.getElementById("answer").value=data.answer

}

function speak(){

const text=document.getElementById("answer").value

const u=new SpeechSynthesisUtterance(text)

u.lang="es-MX"

speechSynthesis.speak(u)

}

function clearAsk(){
document.getElementById("question").value=""
document.getElementById("answer").value=""
}

</script>

</body>
</html>
"""