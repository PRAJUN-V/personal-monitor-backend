from datetime import date, datetime, timedelta
from typing import List
import os

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

import auth
import database  # noqa: F401  (kept for side-effect imports / consistency)
import schemas

# Schema is managed by Alembic migrations (`alembic upgrade head`), which runs
# automatically on deploy. We intentionally do NOT call create_all() here.

app = FastAPI(title="Personal Monitor API", version="1.0.0")

# Allow the Next.js frontend to call this API.
origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def calculate_health_metrics(height_cm: float, weight_kg: float):
    height_m = height_cm / 100
    bmi = round(weight_kg / (height_m ** 2), 2)

    if bmi < 18.5:
        category = "Underweight"
        target_weight = 18.5 * (height_m ** 2)
        diff = round(target_weight - weight_kg, 2)
    elif bmi <= 24.9:
        category = "Normal weight"
        diff = 0.0
    elif bmi <= 29.9:
        category = "Overweight"
        target_weight = 24.9 * (height_m ** 2)
        diff = round(weight_kg - target_weight, 2)
    else:
        category = "Obese"
        target_weight = 24.9 * (height_m ** 2)
        diff = round(weight_kg - target_weight, 2)

    return bmi, category, diff


# ---------------- Auth ----------------
@app.post("/register")
def register(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    db_user = db.query(database.User).filter(database.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    new_user = database.User(
        username=user.username,
        hashed_password=auth.get_password_hash(user.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully"}


@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db),
):
    user = db.query(database.User).filter(database.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    access_token = auth.create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/api/me")
async def read_users_me(current_user: database.User = Depends(auth.get_current_user)):
    return {"username": current_user.username, "is_admin": current_user.is_admin}


# ---------------- Admin: user management ----------------
@app.get("/api/users", response_model=List[schemas.UserResponse])
async def list_users(
    db: Session = Depends(database.get_db),
    _admin: database.User = Depends(auth.get_current_admin),
):
    return db.query(database.User).order_by(database.User.id).all()


@app.post("/api/users", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: schemas.AdminUserCreate,
    db: Session = Depends(database.get_db),
    _admin: database.User = Depends(auth.get_current_admin),
):
    existing = db.query(database.User).filter(database.User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    new_user = database.User(
        username=payload.username,
        hashed_password=auth.get_password_hash(payload.password),
        is_admin=payload.is_admin,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.put("/api/users/{user_id}", response_model=schemas.UserResponse)
async def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(database.get_db),
    admin: database.User = Depends(auth.get_current_admin),
):
    user = db.query(database.User).filter(database.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.username is not None and payload.username != user.username:
        clash = (
            db.query(database.User)
            .filter(database.User.username == payload.username, database.User.id != user_id)
            .first()
        )
        if clash:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = payload.username

    if payload.password is not None:
        user.hashed_password = auth.get_password_hash(payload.password)

    if payload.is_admin is not None:
        # Prevent admins from removing their own admin rights (avoids lockout).
        if user.id == admin.id and payload.is_admin is False:
            raise HTTPException(status_code=400, detail="You cannot revoke your own admin access")
        user.is_admin = payload.is_admin

    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(database.get_db),
    admin: database.User = Depends(auth.get_current_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    user = db.query(database.User).filter(database.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}


# ---------------- Health ----------------
@app.post("/api/health", response_model=schemas.HealthRecordResponse)
async def create_health_record(
    record: schemas.HealthRecordCreate,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    record_data = record.model_dump()
    if record_data["date"]:
        record_data["date"] = datetime.strptime(record_data["date"], "%Y-%m-%d").date()
    else:
        record_data["date"] = date.today()

    new_record = database.HealthRecord(**record_data, user_id=current_user.id)
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    bmi, category, diff = calculate_health_metrics(new_record.height, new_record.weight)
    return {**new_record.__dict__, "bmi": bmi, "category": category, "weight_diff_to_normal": diff}


@app.get("/api/health", response_model=List[schemas.HealthRecordResponse])
async def list_health_records(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    records = (
        db.query(database.HealthRecord)
        .filter(database.HealthRecord.user_id == current_user.id)
        .order_by(database.HealthRecord.date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    response = []
    for r in records:
        bmi, category, diff = calculate_health_metrics(r.height, r.weight)
        response.append(
            {
                "id": r.id,
                "date": r.date,
                "height": r.height,
                "weight": r.weight,
                "bp_systolic": r.bp_systolic,
                "bp_diastolic": r.bp_diastolic,
                "bmi": bmi,
                "category": category,
                "weight_diff_to_normal": diff,
            }
        )
    return response


@app.put("/api/health/{record_id}", response_model=schemas.HealthRecordResponse)
async def update_health_record(
    record_id: int,
    record: schemas.HealthRecordCreate,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    db_record = (
        db.query(database.HealthRecord)
        .filter(
            database.HealthRecord.id == record_id,
            database.HealthRecord.user_id == current_user.id,
        )
        .first()
    )
    if not db_record:
        raise HTTPException(status_code=404, detail="Record not found")

    record_data = record.model_dump()
    if record_data["date"]:
        db_record.date = datetime.strptime(record_data["date"], "%Y-%m-%d").date()
    db_record.height = record_data["height"]
    db_record.weight = record_data["weight"]
    db_record.bp_systolic = record_data["bp_systolic"]
    db_record.bp_diastolic = record_data["bp_diastolic"]

    db.commit()
    db.refresh(db_record)
    bmi, category, diff = calculate_health_metrics(db_record.height, db_record.weight)
    return {**db_record.__dict__, "bmi": bmi, "category": category, "weight_diff_to_normal": diff}


@app.delete("/api/health/{record_id}")
async def delete_health_record(
    record_id: int,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    db_record = (
        db.query(database.HealthRecord)
        .filter(
            database.HealthRecord.id == record_id,
            database.HealthRecord.user_id == current_user.id,
        )
        .first()
    )
    if not db_record:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(db_record)
    db.commit()
    return {"message": "Record deleted successfully"}


# ---------------- Finance ----------------
@app.post("/api/sources", response_model=schemas.SourceResponse)
async def create_source(
    source: schemas.SourceCreate,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    new_source = database.Source(**source.model_dump(), user_id=current_user.id)
    db.add(new_source)
    db.commit()
    db.refresh(new_source)
    return new_source


@app.get("/api/sources", response_model=List[schemas.SourceResponse])
async def list_sources(
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    return db.query(database.Source).filter(database.Source.user_id == current_user.id).all()


@app.put("/api/sources/{source_id}", response_model=schemas.SourceResponse)
async def update_source(
    source_id: int,
    payload: schemas.SourceUpdate,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    source = (
        db.query(database.Source)
        .filter(database.Source.id == source_id, database.Source.user_id == current_user.id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if payload.name is not None:
        source.name = payload.name
    if payload.balance is not None:
        source.balance = payload.balance

    db.commit()
    db.refresh(source)
    return source


@app.post("/api/transactions", response_model=schemas.TransactionResponse)
async def create_transaction(
    transaction: schemas.TransactionCreate,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    source = (
        db.query(database.Source)
        .filter(
            database.Source.id == transaction.source_id,
            database.Source.user_id == current_user.id,
        )
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    trans_data = transaction.model_dump()
    if trans_data["date"]:
        try:
            trans_data["date"] = datetime.fromisoformat(trans_data["date"].replace("Z", "+00:00"))
        except ValueError:
            trans_data["date"] = datetime.strptime(trans_data["date"], "%Y-%m-%d")
    else:
        trans_data["date"] = datetime.utcnow()

    new_transaction = database.Transaction(**trans_data, user_id=current_user.id)

    if new_transaction.type == "income":
        source.balance += new_transaction.amount
    else:
        source.balance -= new_transaction.amount

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    res = schemas.TransactionResponse.model_validate(new_transaction)
    res.source_name = source.name
    return res


@app.get("/api/transactions", response_model=List[schemas.TransactionResponse])
async def list_transactions(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    transactions = (
        db.query(database.Transaction)
        .filter(database.Transaction.user_id == current_user.id)
        .order_by(database.Transaction.date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    response = []
    for t in transactions:
        res = schemas.TransactionResponse.model_validate(t)
        res.source_name = t.source.name if t.source else None
        response.append(res)
    return response


@app.delete("/api/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    db: Session = Depends(database.get_db),
    current_user: database.User = Depends(auth.get_current_user),
):
    trans = (
        db.query(database.Transaction)
        .filter(
            database.Transaction.id == transaction_id,
            database.Transaction.user_id == current_user.id,
        )
        .first()
    )
    if not trans:
        raise HTTPException(status_code=404, detail="Transaction not found")

    source = trans.source
    if source:
        if trans.type == "income":
            source.balance -= trans.amount
        else:
            source.balance += trans.amount

    db.delete(trans)
    db.commit()
    return {"message": "Transaction deleted"}


@app.get("/")
def root():
    return {"status": "ok", "service": "Personal Monitor API"}
