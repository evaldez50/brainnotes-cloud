import os
from openai import OpenAI
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
client = OpenAI()

VECTOR_STORE_ID = "vs_69a34ceb4f488191b243f5a8c56924d9"

class AskRequest(BaseModel):
    question: str

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

    # Extraer texto de respuesta
    out_text = ""
    if response.output and len(response.output) > 0:
        for item in response.output:
            # Algunos items son tool calls, otros son mensajes
            if hasattr(item, "content") and item.content:
                for c in item.content:
                    if getattr(c, "type", None) == "output_text":
                        out_text += c.text

    return {"answer": out_text.strip() or "(sin respuesta)"}