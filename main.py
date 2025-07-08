# main.py
import aiosqlite
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

# --- Configuration ---
DATABASE_NAME = "dictionary.db"
TABLE_NAME = "translations"

# Initialize the FastAPI app
app = FastAPI(
    title="Local Dictionary API",
    description="An API to serve dictionary translations from a local SQLite database.",
    version="1.0.0",
)


# --- Database Connection ---
async def get_db_connection():
    """Gets a connection to the SQLite database."""
    db = await aiosqlite.connect(DATABASE_NAME)
    db.row_factory = aiosqlite.Row
    return db


# --- Pydantic Models (Data Structures) ---
class TranslationEntry(BaseModel):
    entry_id: int
    translations: Dict[str, Optional[str]]


class RawDBEntry(BaseModel):
    ID: int
    class Config:
        extra = "allow"


# --- API Endpoints ---

@app.get("/")
async def read_root():
    """A welcome endpoint to confirm the API is running."""
    return {"message": "Welcome to the Local Dictionary API!"}


@app.get("/languages", response_model=List[str])
async def get_available_languages():
    """Gets the list of available languages from the database table columns."""
    db = await get_db_connection()
    try:
        cursor = await db.execute(f'PRAGMA table_info("{TABLE_NAME}")')
        table_info = await cursor.fetchall()
        await cursor.close()
        excluded_columns = ['id', 'entryid', 'rowid']
        languages = [
            column['name'] for column in table_info
            if column['name'].lower() not in excluded_columns
        ]
        return languages
    finally:
        await db.close()


@app.get("/search/{from_language}/{query}", response_model=Optional[TranslationEntry])
async def search_translation(from_language: str, query: str):
    """Searches for a translation."""
    db = await get_db_connection()
    try:
        sql_query = f'SELECT * FROM "{TABLE_NAME}" WHERE "{from_language}" LIKE ? COLLATE NOCASE LIMIT 1'
        cursor = await db.execute(sql_query, (f'%{query.strip()}%',))
        result = await cursor.fetchone()
        await cursor.close()

        if not result:
            return None

        # --- THIS IS THE FIX ---
        # Convert the sqlite3.Row object to a standard dictionary before parsing.
        raw_entry = RawDBEntry.parse_obj(dict(result))

        response = {
            "entry_id": raw_entry.ID,
            "translations": {k: v for k, v in raw_entry.dict().items() if k != 'ID'}
        }
        return TranslationEntry.parse_obj(response)

    finally:
        await db.close()


@app.get("/suggest/{from_language}/{query}", response_model=List[str])
async def get_search_suggestions(from_language: str, query: str):
    """Gets search suggestions (autocomplete)."""
    if not query.strip():
        return []
    db = await get_db_connection()
    try:
        sql_query = f'SELECT "{from_language}" FROM "{TABLE_NAME}" WHERE "{from_language}" LIKE ? COLLATE NOCASE LIMIT 10'
        cursor = await db.execute(sql_query, (f'{query.strip()}%',))
        results = await cursor.fetchall()
        await cursor.close()
        return [row[from_language] for row in results]
    finally:
        await db.close()


# --- Special Diagnostic Endpoint ---
@app.get("/test-db")
async def test_database_connection():
    """A special endpoint to diagnose database connection and query issues."""
    print("--- Running Database Diagnostic ---")
    db = None
    try:
        db = await get_db_connection()
        print("Step 1: Database connection successful.")
        cursor = await db.execute(f'PRAGMA table_info("{TABLE_NAME}")')
        columns = await cursor.fetchall()
        column_names = [col['name'] for col in columns]
        print(f"Step 2: Successfully fetched columns: {column_names}")
        if not column_names:
            raise Exception(f"The table '{TABLE_NAME}' was found, but it has no columns or does not exist.")
        query = f'SELECT * FROM "{TABLE_NAME}" LIMIT 1'
        cursor = await db.execute(query)
        first_row = await cursor.fetchone()
        await cursor.close()
        if not first_row:
            return {"status": "SUCCESS", "detail": f"Connected to DB and table '{TABLE_NAME}', but the table is empty."}
        print(f"Step 3: Successfully fetched one row: {dict(first_row)}")
        if 'ID' not in first_row.keys():
            return {"status": "ERROR", "detail": f"The column 'ID' was not found. Available columns are: {column_names}"}
        print("Step 4: 'ID' column found.")
        return {"status": "SUCCESS", "detail": "Database connection and basic query are working correctly.", "columns": column_names, "first_row": dict(first_row)}
    except Exception as e:
        print(f"--- DIAGNOSTIC FAILED ---")
        print(f"The error is: {e}")
        return {"status": "ERROR", "detail": str(e)}
    finally:
        if db:
            await db.close()