from fastapi import FastAPI

from app.api.v1 import cases, health, transactions

app = FastAPI(title="FinCrime Intelligence API", version="0.1.0")
app.include_router(health.router, prefix="/api/v1")
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
