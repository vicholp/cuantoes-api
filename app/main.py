from pydantic import BaseModel, Field
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic_settings import BaseSettings, SettingsConfigDict
import anthropic
import json
from bson import ObjectId

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    DATABASE_HOST: str = Field(default='db')
    DATABASE_PORT: int = Field(default=27017)
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    ANTHROPIC_API_KEY: str

settings = Settings(_env_file='prod.env', _env_file_encoding='utf-8')

class Mongo:
    def __init__(self):
        self.client = MongoClient(settings.DATABASE_HOST, settings.DATABASE_PORT, username=settings.DATABASE_USER, password=settings.DATABASE_PASSWORD)
        self.db = self.client["cuantoes"]
        self.receipts = self.db["receipts"]
        self.receipt_items = self.db["receipt_items"]
        self.receipt_items_claims = self.db["receipt_items_claims"]
        self.claimants = self.db["claimants"]

mongo = Mongo()


client = anthropic.Anthropic(
    api_key=settings.ANTHROPIC_API_KEY,
)

class Receipt(BaseModel):
    pass

class ReceiptItem(BaseModel):
    receipt_id: str
    name: str
    price: int

class ReceiptItemClaim(BaseModel):
    item_id: str
    claimant_id: str

class Claimant(BaseModel):
    name: str
    uuid: str

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://192.168.1.8:5173","http://localhost:5173",],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_receipt_items_from_image(image_base64: str):
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20000,
        temperature=1,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": "dame la lista de items, la cantidad y el precio de cada uno, en una json. [\"items\": [{\"name\": \"item name\", \"quantity\": 1, \"total_price\": 1000}],...] Responde solo json sin formato"
                    }
                ]
            }
        ]
    )

    text = message.content[0].text

    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    data =  json.loads(text)

    return data

@app.post('/receipts')
def create_receipt(body: dict):
    items = get_receipt_items_from_image(body['image_base64'])

    items = items.get('items', [])

    receipt = mongo.receipts.insert_one({})

    receipt_id = str(receipt.inserted_id)

    for item in items:
        for i in range(item.get("quantity", 1)):
            mongo.receipt_items.insert_one({
                "receipt_id": receipt_id,
                "name": item["name"],
                "price": item["total_price"] / item["quantity"]
            })
    
    return {"receipt_id": receipt_id}
        
@app.get('/receipts/{receipt_id}/items')
def get_receipt_items(receipt_id: str):
    items = list(mongo.receipt_items.find({"receipt_id": receipt_id}))

    for item in items:
        item["_id"] = str(item["_id"])

    for item in items:
        claims = list(mongo.receipt_items_claims.find({"item_id": item["_id"]}))

        new_claims = []

        for claim in claims:
            claim["_id"] = str(claim["_id"])
            claimant = mongo.claimants.find_one({"_id": ObjectId(claim["claimant_id"])})
            if claimant:
                claimant["_id"] = str(claimant["_id"])
            claim["claimant"] = claimant
            new_claims.append(claim)
        
        item["claims"] = claims

    return items

@app.post('/receipts/{receipt_id}/items/{item_id}/claim')
def claim_receipt_item(receipt_id: str, item_id: str, body: dict):
    claimant_uuid = body.get("claimant_uuid")

    claimant = mongo.claimants.find_one({"uuid": claimant_uuid})

    claimed_item = mongo.receipt_items_claims.find_one({"item_id": item_id, "claimant_id": str(claimant["_id"])})

    if claimed_item is not None:
        mongo.receipt_items_claims.delete_one({"_id": claimed_item["_id"]})
        return {"status": "Reclamación eliminada exitosamente."}
    
    claim = {
        "item_id": item_id,
        "claimant_id": str(claimant["_id"])
    }

    mongo.receipt_items_claims.insert_one(claim)

    return {"status": "Item reclamado exitosamente."}

@app.post('/claimants/{claimant_uuid}')
def upsert_claimant(claimant_uuid: str, body: dict):
    claimant = mongo.claimants.find_one({"uuid": claimant_uuid})

    if claimant is None:
        mongo.claimants.insert_one({
            "name": body.get("name"),
            "uuid": claimant_uuid
        })
        return {"status": "Reclamante creado exitosamente."}
    
    mongo.claimants.update_one(
        {"uuid": claimant_uuid},
        {"$set": {"name": body.get("name")}}
    )

    return {"status": "Reclamante actualizado exitosamente."}