from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import smtplib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib import error, request as urllib_request
from urllib.parse import quote as url_quote

from PIL import Image, ImageDraw, ImageFont
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from matplotlib import font_manager
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "style_sense.db"
GENERATED_DIR = BASE_DIR / "generated"
OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
CLOUDFLARE_API_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
OPENROUTER_ANALYSIS_MODEL = os.environ.get(
    "OPENROUTER_ANALYSIS_MODEL",
    "openrouter/free",
).strip()
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
DEFAULT_CLOUDFLARE_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
DEFAULT_LOCAL_IMAGE_MODEL = os.environ.get(
    "LOCAL_IMAGE_MODEL",
    "RunDiffusion/Juggernaut-XL-v9",
).strip()
POLICY_VERSION = os.environ.get("STYLE_SENSE_POLICY_VERSION", "2026-08-20")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

QUESTIONNAIRE_LIMITS = {
    "height": (140, 220, "Рост должен быть от 140 до 220 см."),
    "weight": (35, 220, "Вес должен быть от 35 до 220 кг."),
    "age": (14, 100, "Возраст должен быть от 14 до 100 лет."),
    "bust": (60, 150, "Обхват груди должен быть от 60 до 150 см."),
    "waist": (45, 140, "Обхват талии должен быть от 45 до 140 см."),
    "hips": (60, 160, "Обхват бёдер должен быть от 60 до 160 см."),
}

QUESTIONNAIRE_OPTIONS = {
    "gender": {"Женский", "Мужской"},
    "limb_length": {"Длинные", "Пропорциональные", "Коротковатые"},
    "cheekbones": {"Ярко выраженные подтянутые", "Мягкие", "Невыраженные"},
    "body_shape": {
        "Жилистое худое",
        "Симметричное пропорциональное",
        "Округлое пышное",
        "Спортивное мускулинное",
    },
    "lip_size": {"Узкие", "Средние", "Пухлые"},
    "hair_texture": {"Прямые", "Волнистые", "Кудрявые"},
    "eyes": {"Карие", "Голубые", "Зеленые", "Серые"},
    "hair": {"Темные", "Русые", "Светлые", "Рыжие"},
    "skin": {"Светлый", "Средний", "Теплый", "Оливковый", "Темный"},
}

app = Flask(
    __name__,
    static_folder=".",
    static_url_path="",
    template_folder="templates",
)
app.config["SECRET_KEY"] = os.environ.get(
    "STYLE_SENSE_SECRET", "style-sense-local-secret"
)


@dataclass(frozen=True)
class LookDirection:
    title: str
    vibe: str
    styling_note: str
    scene_note: str


@dataclass(frozen=True)
class KibbeArchetype:
    name: str
    line: str
    clothing: str
    avoid: str


@dataclass(frozen=True)
class EventStyleBrief:
    category: str
    outfit: str
    footwear: str
    accessories: str
    avoid: str
    scene: str


KIBBE_ARCHETYPES: dict[str, KibbeArchetype] = {
    "ДРАМАТИК": KibbeArchetype(
        name="ДРАМАТИК",
        line="длинная вертикаль, узкий силуэт, острые геометричные линии",
        clothing="строгий крой, удлиненные жакеты, прямые брюки, гладкие плотные ткани, минималистичная графика",
        avoid="мелкий декор, чрезмерная мягкость, бесформенные объемы и романтичные оборки",
    ),
    "МЯГКИЙ ДРАМАТИК": KibbeArchetype(
        name="МЯГКИЙ ДРАМАТИК",
        line="длинная вертикаль с мягкой округлостью и выразительной талией",
        clothing="драпировки, удлиненные линии, акцент талии, дорогие текучие ткани, крупные элегантные детали",
        avoid="мелкую дробность, сухой минимализм без формы и короткие обрезанные линии",
    ),
    "ЯРКИЙ ДРАМАТИК": KibbeArchetype(
        name="ЯРКИЙ ДРАМАТИК",
        line="компактная вертикаль с остротой, сухостью и динамикой",
        clothing="четкие плечи, контрастные детали, короткие структурные жакеты, графичные линии, собранные комплекты",
        avoid="тяжелую романтичность, мягкие бесформенные ткани и слишком спокойную классику",
    ),
    "НАТУРАЛ": KibbeArchetype(
        name="НАТУРАЛ",
        line="прямая расслабленная линия, естественная ширина и умеренная структура",
        clothing="свободные жакеты, прямые брюки, фактурный трикотаж, натуральные ткани, легкая небрежность",
        avoid="чрезмерно обтягивающие силуэты, хрупкий мелкий декор и жесткую театральность",
    ),
    "МЯГКИЙ НАТУРАЛ": KibbeArchetype(
        name="МЯГКИЙ НАТУРАЛ",
        line="естественная расслабленность с мягкими округлыми линиями",
        clothing="мягкие рубашки, пластичные жакеты, полуприлегающие силуэты, фактура, мягкий акцент талии",
        avoid="слишком жесткую геометрию, тонкие хрупкие детали и перегруженный декор",
    ),
    "ЯРКИЙ НАТУРАЛ": KibbeArchetype(
        name="ЯРКИЙ НАТУРАЛ",
        line="длинная свободная линия, заметная ширина и крупный масштаб",
        clothing="oversize-пальто, широкие брюки, крупные фактуры, длинные слои, расслабленная посадка",
        avoid="миниатюрную дробность, слишком тесный крой и мелкую романтичную отделку",
    ),
    "КЛАССИК": KibbeArchetype(
        name="КЛАССИК",
        line="баланс, симметрия, умеренная посадка и чистые пропорции",
        clothing="лаконичные костюмы, прямые юбки и брюки, аккуратные пальто, спокойные ткани, точная посадка",
        avoid="крайности: чрезмерный oversize, слишком острый драматизм и избыточную романтичность",
    ),
    "МЯГКИЙ КЛАССИК": KibbeArchetype(
        name="МЯГКИЙ КЛАССИК",
        line="классический баланс с мягкостью, плавностью и деликатной талией",
        clothing="мягкая классика, аккуратные жакеты, текучие блузы, юбки миди, мягко очерченная талия",
        avoid="резкую геометрию, грубые фактуры, слишком крупный масштаб и тяжелый oversize",
    ),
    "РОМАНТИК": KibbeArchetype(
        name="РОМАНТИК",
        line="округлые линии, выраженная талия, мягкость и компактность",
        clothing="драпировки, мягкие платья, подчёркнутая талия, пластичные ткани, округлые детали",
        avoid="сухой мужской крой, прямые бесформенные силуэты и жесткую угловатость",
    ),
    "ЯРКИЙ РОМАНТИК": KibbeArchetype(
        name="ЯРКИЙ РОМАНТИК",
        line="компактная округлость с ярким акцентом и выразительной талией",
        clothing="фигурные жакеты, акцентная талия, мягкие ткани, небольшие выразительные детали, изящный контраст",
        avoid="длинную сухую вертикаль, крупный oversize и бесформенную простоту",
    ),
    "ГАМИН": KibbeArchetype(
        name="ГАМИН",
        line="компактность, угловатость, дробные линии и энергичный контраст",
        clothing="укороченные жакеты, графичные комплекты, контраст верха и низа, четкие детали, компактные аксессуары",
        avoid="длинные монотонные линии, тяжелые драпировки и крупный расслабленный oversize",
    ),
    "МЯГКИЙ ГАМИН": KibbeArchetype(
        name="МЯГКИЙ ГАМИН",
        line="компактная линия с мягкой округлостью и живым контрастом",
        clothing="укороченные слои, мягкая посадка, акцент талии, небольшие выразительные детали, playful chic",
        avoid="слишком длинные прямые силуэты, тяжелую классику и полностью бесформенную одежду",
    ),
    "ЯРКИЙ ГАМИН": KibbeArchetype(
        name="ЯРКИЙ ГАМИН",
        line="компактность, выразительность, четкий контраст и небольшая театральность",
        clothing="короткие структурные формы, контрастные блоки, необычные детали, графичные аксессуары",
        avoid="однотонную длинную вертикаль, мягкую расплывчатость и чрезмерно спокойные комплекты",
    ),
}


LOOK_DIRECTIONS: tuple[LookDirection, ...] = (
    LookDirection(
        title="Neural Power Tailoring",
        vibe="Сильный структурный образ",
        styling_note="sharp tailoring, elongated silhouette, premium layering, quiet luxury details",
        scene_note="clean futuristic fashion studio, full-body model, editorial lighting, realistic premium fabrics",
    ),
    LookDirection(
        title="Soft Violet Chic",
        vibe="Мягкая женственная современность",
        styling_note="fluid fabrics, softened waistline, elegant drape, polished accessories",
        scene_note="luxury lookbook photo, soft lilac ambient light, standing model, realistic beauty styling",
    ),
    LookDirection(
        title="Executive Minimal",
        vibe="Собранный минимализм",
        styling_note="minimal wardrobe, monochrome coordination, crisp lines, refined shoes and bag",
        scene_note="high-end city editorial, full-height composition, realistic model pose, premium retouching",
    ),
    LookDirection(
        title="Evening Aura",
        vibe="Вечерний выразительный выход",
        styling_note="occasion-ready silhouette, statement finishing, elegant shine, balanced glamour",
        scene_note="luxury event photography, full-body frame, cinematic but realistic lighting, fashion campaign quality",
    ),
    LookDirection(
        title="Creative Gallery",
        vibe="Творческий интеллектуальный look",
        styling_note="artful proportions, layered textures, directional styling, elegant contrast",
        scene_note="gallery-inspired fashion set, modern editorial composition, single realistic fashion model",
    ),
    LookDirection(
        title="Smart Casual Sync",
        vibe="Умный повседневный баланс",
        styling_note="smart casual outfit, clean layering, practical elegance, contemporary proportions",
        scene_note="premium lifestyle shoot, full-body standing pose, realistic soft daylight, polished styling",
    ),
    LookDirection(
        title="Date Night Signal",
        vibe="Привлекательный и уверенный образ",
        styling_note="flattering silhouette, romantic details, premium textures, tasteful accessories",
        scene_note="fashion portrait with full-body framing, intimate evening atmosphere, realistic skin and fabric rendering",
    ),
    LookDirection(
        title="Avant Office",
        vibe="Современный офисный акцент",
        styling_note="office-ready wardrobe with a modern twist, clean geometry, elevated basics, luxury restraint",
        scene_note="designer workspace set, editorial fashion production, realistic model proportions, polished lighting",
    ),
    LookDirection(
        title="Weekend Sculpt",
        vibe="Свободный образ с формой",
        styling_note="relaxed but sculpted silhouette, comfortable layers, premium knitwear or denim, intentional styling",
        scene_note="street-style editorial, full-body shot, subtle motion, believable premium apparel photography",
    ),
    LookDirection(
        title="Signature Presence",
        vibe="Фирменный standout-образ",
        styling_note="distinctive statement look, cohesive palette, expressive styling, memorable details",
        scene_note="fashion campaign hero shot, single realistic fashion model, luxurious and realistic image output, no collage",
    ),
)

MALE_LOOK_DIRECTIONS: tuple[LookDirection, ...] = (
    LookDirection(
        title="Structured Menswear",
        vibe="Структурный мужской образ",
        styling_note="masculine tailoring, structured jacket, clean trousers, strong shoulder line, premium menswear proportions",
        scene_note="single male model lookbook photo, full-body outfit shot, warm studio light, no other people",
    ),
    LookDirection(
        title="Soft Modern Layering",
        vibe="Мягкая мужская многослойность",
        styling_note="soft masculine layers, relaxed knit or shirt, clean outerwear, balanced fit without feminine garments",
        scene_note="single male model in a realistic premium studio, neutral background, natural fabric folds",
    ),
    LookDirection(
        title="Executive Minimal",
        vibe="Собранный мужской минимализм",
        styling_note="minimal menswear, crisp shirt, tailored trousers, restrained palette, refined shoes",
        scene_note="one male model, full outfit visible, clean editorial menswear photography, no catalog lineup",
    ),
    LookDirection(
        title="Evening Tailoring",
        vibe="Вечерний мужской выход",
        styling_note="evening menswear, elegant jacket or overshirt, polished trousers, subtle texture, confident silhouette",
        scene_note="single male model in evening editorial lighting, one outfit only, realistic clothing details",
    ),
    LookDirection(
        title="Creative Gallery",
        vibe="Творческий мужской look",
        styling_note="artful masculine proportions, textured overshirt or jacket, contemporary trousers, expressive but wearable details",
        scene_note="one male model at a minimal gallery-inspired set, full-body frame, no women, no group",
    ),
    LookDirection(
        title="Smart Casual Sync",
        vibe="Умный мужской casual",
        styling_note="smart casual menswear, clean layering, practical elegance, loafers or minimal sneakers, modern fit",
        scene_note="single male model lifestyle lookbook shot, realistic daylight, one complete outfit",
    ),
    LookDirection(
        title="Date Night Menswear",
        vibe="Привлекательный мужской образ",
        styling_note="flattering masculine outfit, knit polo or shirt, tailored trousers, premium texture, confident restrained styling",
        scene_note="one male model, tasteful evening atmosphere, face can be cropped, focus on clothes and proportions",
    ),
    LookDirection(
        title="Avant Office",
        vibe="Современный офисный акцент",
        styling_note="office-ready menswear with a modern twist, clean geometry, elevated basics, structured but comfortable fit",
        scene_note="single male model in a designer workspace, full outfit visible, realistic menswear editorial",
    ),
    LookDirection(
        title="Weekend Sculpt",
        vibe="Свободный мужской образ с формой",
        styling_note="relaxed masculine silhouette, premium denim or knitwear, layered jacket, intentional casual styling",
        scene_note="one male model street-style editorial, full-body shot, no duplicated person, no split image",
    ),
    LookDirection(
        title="Signature Presence",
        vibe="Фирменный мужской standout-образ",
        styling_note="distinctive masculine statement look, cohesive palette, memorable outer layer, realistic wearable garments",
        scene_note="single male model campaign-style photo, premium realistic image, one outfit only",
    ),
)


def look_directions_for_profile(profile: dict[str, str]) -> tuple[LookDirection, ...]:
    if profile.get("gender") == "Мужской":
        return MALE_LOOK_DIRECTIONS
    return LOOK_DIRECTIONS


def load_local_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(_: object | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


load_local_env()


def init_db() -> None:
    GENERATED_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS questionnaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            gender TEXT NOT NULL DEFAULT '',
            height TEXT NOT NULL DEFAULT '',
            weight TEXT NOT NULL DEFAULT '',
            age TEXT NOT NULL DEFAULT '',
            proportions TEXT NOT NULL DEFAULT '',
            limb_length TEXT NOT NULL DEFAULT '',
            cheekbones TEXT NOT NULL DEFAULT '',
            body_shape TEXT NOT NULL DEFAULT '',
            lip_size TEXT NOT NULL DEFAULT '',
            hair_texture TEXT NOT NULL DEFAULT '',
            bust TEXT NOT NULL DEFAULT '',
            waist TEXT NOT NULL DEFAULT '',
            hips TEXT NOT NULL DEFAULT '',
            eyes TEXT NOT NULL DEFAULT '',
            hair TEXT NOT NULL DEFAULT '',
            skin TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '',
            preferred_colors TEXT NOT NULL DEFAULT '',
            style_goals TEXT NOT NULL DEFAULT '',
            extra_preferences TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            look_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, look_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS generated_looks (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            vibe TEXT NOT NULL,
            meta TEXT NOT NULL,
            note TEXT NOT NULL,
            profile_note TEXT NOT NULL,
            reason TEXT NOT NULL,
            prompt TEXT NOT NULL,
            image_path TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'ai',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS password_reset_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS consent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT NULL,
            email TEXT NOT NULL DEFAULT '',
            consent_type TEXT NOT NULL,
            consent_version TEXT NOT NULL,
            source_page TEXT NOT NULL DEFAULT '',
            ip_address TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        """
    )

    ensure_column(db, "questionnaires", "gender", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "age", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "proportions", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "limb_length", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "cheekbones", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "body_shape", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "lip_size", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "hair_texture", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "bust", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "waist", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "hips", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "preferred_colors", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "style_goals", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "questionnaires", "extra_preferences", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "generated_looks", "source", "TEXT NOT NULL DEFAULT 'ai'")
    backfill_legacy_questionnaire_columns(db)

    db.commit()
    db.close()


def ensure_column(db: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = table_columns(db, table_name)
    if column_name not in columns:
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def table_columns(db: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def backfill_legacy_questionnaire_columns(db: sqlite3.Connection) -> None:
    columns = table_columns(db, "questionnaires")

    if "mood" in columns:
        db.execute(
            """
            UPDATE questionnaires
            SET style_goals = mood
            WHERE style_goals = '' AND mood != ''
            """
        )
    if "palette" in columns:
        db.execute(
            """
            UPDATE questionnaires
            SET preferred_colors = palette
            WHERE preferred_colors = '' AND palette != ''
            """
        )
    if "extra_wishes" in columns:
        db.execute(
            """
            UPDATE questionnaires
            SET extra_preferences = extra_wishes
            WHERE extra_preferences = '' AND extra_wishes != ''
            """
        )


def current_user_id() -> int | None:
    user_id = session.get("user_id")
    return int(user_id) if user_id else None


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def log_consent_event(
    consent_type: str,
    *,
    user_id: int | None = None,
    email: str = "",
    source_page: str = "",
) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO consent_logs (
            user_id, email, consent_type, consent_version, source_page, ip_address, user_agent
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            email.strip().lower(),
            consent_type,
            POLICY_VERSION,
            source_page,
            client_ip(),
            request.headers.get("User-Agent", ""),
        ),
    )
    db.commit()


def fetch_user(user_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, email FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def fetch_questionnaire(user_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        """
        SELECT
            gender,
            height,
            weight,
            age,
            proportions,
            limb_length,
            cheekbones,
            body_shape,
            lip_size,
            hair_texture,
            bust,
            waist,
            hips,
            eyes,
            hair,
            skin,
            event_type,
            preferred_colors,
            style_goals,
            extra_preferences
        FROM questionnaires
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()


def fetch_favorites(user_id: int) -> set[str]:
    rows = get_db().execute(
        "SELECT look_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return {row["look_id"] for row in rows}


def fetch_generated_looks(
    user_id: int, favorites: set[str] | None = None
) -> list[dict[str, Any]]:
    favorites = favorites or set()
    rows = get_db().execute(
        """
        SELECT id, title, vibe, meta, note, profile_note, reason, prompt, image_path, source
        FROM generated_looks
        WHERE user_id = ?
        ORDER BY created_at ASC
        """,
        (user_id,),
    ).fetchall()

    return [
        localize_saved_look(
            {
            "id": row["id"],
            "title": row["title"],
            "vibe": row["vibe"],
            "meta": row["meta"],
            "tags": [tag.strip() for tag in row["meta"].split("•") if tag.strip()][:3],
            "note": row["note"],
            "profile_note": row["profile_note"],
            "reason": row["reason"],
            "prompt": row["prompt"],
            "image": f'/{row["image_path"]}?v={row["id"]}',
            "imagePosition": "center center",
            "source": row["source"],
            "isFavorite": row["id"] in favorites,
            }
        )
        for row in rows
    ]


def fetch_generated_look(user_id: int, look_id: str) -> dict[str, Any] | None:
    row = get_db().execute(
        """
        SELECT id, title, vibe, meta, note, profile_note, reason, prompt, image_path, source
        FROM generated_looks
        WHERE user_id = ? AND id = ?
        """,
        (user_id, look_id),
    ).fetchone()
    if row is None:
        return None

    favorites = fetch_favorites(user_id)
    return localize_saved_look({
        "id": row["id"],
        "title": row["title"],
        "vibe": row["vibe"],
        "meta": row["meta"],
        "tags": [tag.strip() for tag in row["meta"].split("•") if tag.strip()][:3],
        "note": row["note"],
        "profile_note": row["profile_note"],
        "reason": row["reason"],
        "prompt": row["prompt"],
        "image": f'/{row["image_path"]}?v={row["id"]}',
        "source": row["source"],
        "is_favorite": row["id"] in favorites,
    })


def clear_generated_looks(user_id: int) -> None:
    rows = get_db().execute(
        "SELECT image_path FROM generated_looks WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    for row in rows:
        file_path = BASE_DIR / row["image_path"]
        if file_path.exists():
            file_path.unlink()

    db = get_db()
    db.execute("DELETE FROM favorites WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM generated_looks WHERE user_id = ?", (user_id,))
    db.commit()


def save_generated_look(
    user_id: int,
    title: str,
    vibe: str,
    meta: str,
    note: str,
    profile_note: str,
    reason: str,
    prompt: str,
    image_bytes: bytes,
    source: str,
) -> str:
    look_id = str(uuid.uuid4())
    filename = f"{look_id}.png"
    relative_path = f"generated/{filename}"
    absolute_path = GENERATED_DIR / filename
    absolute_path.write_bytes(image_bytes)

    get_db().execute(
        """
        INSERT INTO generated_looks (
            id, user_id, title, vibe, meta, note, profile_note, reason, prompt, image_path, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            look_id,
            user_id,
            title,
            vibe,
            meta,
            note,
            profile_note,
            reason,
            prompt,
            relative_path,
            source,
        ),
    )
    get_db().commit()
    return look_id


def profile_payload(user_id: int) -> dict[str, Any]:
    user = fetch_user(user_id)
    if user is None:
        return {"authenticated": False}

    questionnaire = fetch_questionnaire(user_id)
    favorites = fetch_favorites(user_id)
    looks = fetch_generated_looks(user_id, favorites)

    data: dict[str, Any] = {
        "authenticated": True,
        "user": {"email": user["email"]},
        "favoritesCount": len(favorites),
        "favorites": list(favorites),
        "questionnaire": None,
        "looks": looks,
    }

    if questionnaire is not None:
        data["questionnaire"] = {
            "gender": questionnaire["gender"],
            "height": questionnaire["height"],
            "weight": questionnaire["weight"],
            "age": questionnaire["age"],
            "proportions": questionnaire["proportions"],
            "limb_length": questionnaire["limb_length"],
            "cheekbones": questionnaire["cheekbones"],
            "body_shape": questionnaire["body_shape"],
            "lip_size": questionnaire["lip_size"],
            "hair_texture": questionnaire["hair_texture"],
            "bust": questionnaire["bust"],
            "waist": questionnaire["waist"],
            "hips": questionnaire["hips"],
            "eyes": questionnaire["eyes"],
            "hair": questionnaire["hair"],
            "skin": questionnaire["skin"],
            "event": questionnaire["event_type"],
            "preferred_colors": questionnaire["preferred_colors"],
            "style_goals": questionnaire["style_goals"],
            "extra_preferences": questionnaire["extra_preferences"],
        }

    return data


def json_error(message: str, status_code: int = 400):
    response = jsonify({"error": message})
    response.status_code = status_code
    return response


def humanize_generation_error(message: str) -> str:
    lower_message = message.lower()
    if "nsfw" in lower_message or "safety" in lower_message:
        return (
            "Генератор заблокировал запрос safety-фильтром. Обычно это происходит из-за сочетания "
            "возраста младше 18 лет, параметров фигуры и взрослого контекста вроде клуба/вечеринки. "
            "Я уже смягчил промпт для безопасной fashion-визуализации: попробуйте сгенерировать ещё раз."
        )
    return message


def parse_questionnaire_number(value: Any, field: str) -> tuple[float | None, str | None]:
    raw_value = str(value or "").strip().replace(",", ".")
    match = re.fullmatch(r"\d+(?:\.\d+)?(?:\s*(?:см|кг|лет|год|года)?)?", raw_value, re.IGNORECASE)
    if match is None:
        return None, "Введите числовое значение без лишних символов."

    number_match = re.search(r"\d+(?:\.\d+)?", raw_value)
    if number_match is None:
        return None, "Введите числовое значение."

    number = float(number_match.group())
    minimum, maximum, error_message = QUESTIONNAIRE_LIMITS[field]
    if number < minimum or number > maximum:
        return None, error_message
    return number, None


def validate_body_consistency(values: dict[str, float]) -> str | None:
    height = values["height"]
    weight = values["weight"]
    bust = values["bust"]
    waist = values["waist"]
    hips = values["hips"]
    height_m = height / 100
    bmi = weight / (height_m * height_m)

    if bmi < 14 or bmi > 55:
        return "Проверьте рост и вес: сочетание выглядит нереалистично."

    if bust > height * 0.78:
        return "Проверьте обхват груди: значение слишком большое для указанного роста."

    if waist > height * 0.72:
        return "Проверьте обхват талии: значение слишком большое для указанного роста."

    if hips > height * 0.86:
        return "Проверьте обхват бёдер: значение слишком большое для указанного роста."

    if max(bust, waist, hips) > weight * 2.15 + 10:
        return "Проверьте вес и обхваты: сочетание выглядит нереалистично."

    if abs(bust - hips) > 45:
        return "Проверьте обхваты груди и бёдер: разница выглядит нереалистично."

    if waist > max(bust, hips) + 20:
        return "Проверьте обхват талии: значение слишком сильно выбивается из пропорций."

    if waist < min(bust, hips) - 55:
        return "Проверьте обхват талии: разница с грудью и бёдрами выглядит нереалистично."

    return None


def validate_questionnaire_payload(payload: dict[str, Any]) -> tuple[dict[str, str] | None, str | None]:
    normalized: dict[str, str] = {}

    for field, options in QUESTIONNAIRE_OPTIONS.items():
        value = str(payload.get(field, "")).strip()
        if value not in options:
            return None, "Выберите значение из списка, а не вводите его вручную."
        normalized[field] = value

    numeric_values: dict[str, float] = {}
    for field in QUESTIONNAIRE_LIMITS:
        number, error_message = parse_questionnaire_number(payload.get(field), field)
        if error_message is not None or number is None:
            return None, error_message
        numeric_values[field] = number
        normalized[field] = str(int(number)) if number.is_integer() else str(number)

    consistency_error = validate_body_consistency(numeric_values)
    if consistency_error is not None:
        return None, consistency_error

    preferred_colors = str(payload.get("preferred_colors", "")).strip()
    if not 2 <= len(preferred_colors) <= 120:
        return None, "Укажите предпочтительные цвета текстом до 120 символов."
    normalized["preferred_colors"] = preferred_colors

    event = str(payload.get("event", "")).strip()
    if not 2 <= len(event) <= 160:
        return None, "Опишите тип мероприятия текстом до 160 символов."
    normalized["event"] = event

    extra_preferences = str(payload.get("extra_preferences", "")).strip()
    if len(extra_preferences) > 600:
        return None, "Дополнительные предпочтения должны быть короче 600 символов."
    normalized["extra_preferences"] = extra_preferences

    return normalized, None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_reset_url(token: str) -> str:
    base_url = os.environ.get("STYLE_SENSE_APP_URL", "http://127.0.0.1:5000").rstrip("/")
    return f"{base_url}/reset-password/{token}"


def create_password_reset_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hash_reset_token(token)
    expires_at = (utc_now() + timedelta(hours=1)).isoformat()

    db = get_db()
    db.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
        (utc_now().isoformat(), user_id),
    )
    db.execute(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (user_id, token_hash, expires_at),
    )
    db.commit()
    return token


def hash_reset_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create_password_reset_code(user_id: int) -> str:
    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = hash_reset_code(code)
    expires_at = (utc_now() + timedelta(minutes=15)).isoformat()

    db = get_db()
    db.execute(
        "UPDATE password_reset_codes SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
        (utc_now().isoformat(), user_id),
    )
    db.execute(
        """
        INSERT INTO password_reset_codes (user_id, code_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (user_id, code_hash, expires_at),
    )
    db.commit()
    return code


def find_valid_password_reset_code(email: str, code: str) -> sqlite3.Row | None:
    row = get_db().execute(
        """
        SELECT prc.id, prc.user_id, prc.expires_at, prc.used_at
        FROM password_reset_codes prc
        JOIN users u ON u.id = prc.user_id
        WHERE u.email = ? AND prc.code_hash = ?
        ORDER BY prc.created_at DESC
        LIMIT 1
        """,
        (email, hash_reset_code(code)),
    ).fetchone()
    if row is None:
        return None
    if row["used_at"]:
        return None
    if datetime.fromisoformat(row["expires_at"]) < utc_now():
        return None
    return row


def send_password_reset_email(email: str, code: str) -> tuple[bool, str | None]:
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_from = os.environ.get("SMTP_FROM", smtp_username).strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").strip().lower() != "false"
    smtp_use_ssl = os.environ.get("SMTP_USE_SSL", "false").strip().lower() == "true" or smtp_port == 465

    if not smtp_host or not smtp_username or not smtp_password or not smtp_from:
        return False, "SMTP не настроен"

    message = EmailMessage()
    message["Subject"] = "ELAN TECH: код восстановления пароля"
    message["From"] = smtp_from
    message["To"] = email
    message["Reply-To"] = smtp_from
    message.set_content(
        "Вы запросили восстановление пароля в ELAN TECH.\n\n"
        f"Ваш код для сброса пароля: {code}\n\n"
        "Код действует 15 минут."
    )
    message.add_alternative(
        f"""
        <html>
          <body style="font-family:Arial,sans-serif;background:#0b0716;color:#f5f0ff;padding:24px;">
            <div style="max-width:560px;margin:0 auto;padding:24px;border-radius:20px;background:#140a28;border:1px solid rgba(182,146,255,.18)">
              <h2 style="margin:0 0 16px;font-size:24px;">ELAN TECH</h2>
              <p style="margin:0 0 16px;line-height:1.6;">Вы запросили восстановление пароля.</p>
              <p style="margin:0 0 8px;line-height:1.6;">Ваш код для сброса пароля:</p>
              <div style="font-size:32px;letter-spacing:8px;font-weight:700;padding:16px 20px;border-radius:16px;background:#1f123d;text-align:center;margin:0 0 16px;">{code}</div>
              <p style="margin:0;line-height:1.6;color:#b6add4;">Код действует 15 минут. Если вы не запрашивали восстановление, просто игнорируйте это письмо.</p>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )

    try:
        if smtp_use_ssl:
            smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        with smtp as client:
            client.ehlo()
            if smtp_use_tls and not smtp_use_ssl:
                client.starttls()
                client.ehlo()
            client.login(smtp_username, smtp_password)
            client.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        return False, "SMTP authentication failed: проверьте логин и пароль приложения Mail.ru."
    except smtplib.SMTPConnectError as exc:
        return False, f"SMTP connect error: {exc}"
    except smtplib.SMTPException as exc:
        return False, f"SMTP error: {exc}"
    except OSError as exc:
        return False, f"Network error: {exc}"
    except Exception as exc:
        return False, str(exc)

    return True, None


def find_valid_password_reset(token: str) -> sqlite3.Row | None:
    token_hash = hash_reset_token(token)
    row = get_db().execute(
        """
        SELECT id, user_id, expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash = ?
        """,
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    if row["used_at"]:
        return None
    if datetime.fromisoformat(row["expires_at"]) < utc_now():
        return None
    return row


def extract_json_object(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = raw_text[start : end + 1]
        parsed = json.loads(snippet)
        if isinstance(parsed, dict):
            return parsed

    raise RuntimeError("Не удалось разобрать JSON-ответ модели анализа анкеты.")


def summarize_hf_error(details: str, status_code: int | None = None) -> str:
    details = details.strip()
    prefix = f"Hugging Face error {status_code}: " if status_code else "Hugging Face error: "

    if not details:
        return prefix + "empty error response"

    try:
        parsed = json.loads(details)
    except json.JSONDecodeError:
        compact = details.replace("\n", " ").strip()
        return prefix + compact[:500]

    if isinstance(parsed, dict):
        message = parsed.get("error") or parsed.get("message") or parsed.get("detail")
        if isinstance(message, dict):
            message = json.dumps(message, ensure_ascii=False)
        if isinstance(message, list):
            message = json.dumps(message, ensure_ascii=False)
        if message:
            return prefix + str(message)
        return prefix + json.dumps(parsed, ensure_ascii=False)[:500]

    return prefix + json.dumps(parsed, ensure_ascii=False)[:500]


def call_openrouter_text_model(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 900,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Для анализа анкеты через OpenRouter задайте OPENROUTER_API_KEY.")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    request_obj = urllib_request.Request(
        OPENROUTER_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("STYLE_SENSE_APP_URL", "http://127.0.0.1:5000"),
            "X-Title": "Style Sense AI",
        },
    )

    try:
        with urllib_request.urlopen(request_obj, timeout=180) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(details)
            api_message = parsed.get("error", {}).get("message")
        except json.JSONDecodeError:
            api_message = None
        raise RuntimeError(
            api_message or "OpenRouter вернул ошибку при анализе анкеты."
        ) from exc
    except error.URLError as exc:
        raise RuntimeError("Не удалось подключиться к OpenRouter для анализа анкеты.") from exc

    choices = response_data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter не вернул ответ для анализа анкеты.")

    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content).strip()


def analyze_profile_with_openrouter(profile: dict[str, str]) -> dict[str, Any]:
    system_prompt = (
        "You are a senior personal stylist. Analyze the user's questionnaire and produce a compact JSON brief "
        "that an image-generation model can reliably use to create appropriate outfit recommendations. "
        "Return JSON only with the following keys: silhouette_strategy, palette_strategy, outfit_focus, "
        "footwear, accessories, styling_notes, avoid, rationale."
    )
    user_prompt = (
        "User questionnaire:\n"
        f"- Gender: {profile['gender']}\n"
        f"- Age: {profile['age']}\n"
        f"- Limb length relative to body: {profile.get('limb_length', '')}\n"
        f"- Cheekbones: {profile.get('cheekbones', '')}\n"
        f"- Height: {profile['height']}\n"
        f"- Weight: {profile['weight']}\n"
        f"- Upper circumference: {profile['bust']}\n"
        f"- Waist: {profile['waist']}\n"
        f"- Lower circumference: {profile['hips']}\n"
        f"- Body shape: {profile.get('body_shape', '')}\n"
        f"- Facial softness: {profile.get('lip_size', '')}\n"
        f"- Hair texture: {profile.get('hair_texture', '')}\n"
        f"- Eyes: {profile['eyes']}\n"
        f"- Hair: {profile['hair']}\n"
        f"- Skin: {profile['skin']}\n"
        f"- Event: {profile['event']}\n"
        f"- Preferred colors: {profile['preferred_colors']}\n"
        f"- Desired impression: {profile['style_goals']}\n"
        f"- Extra preferences: {profile['extra_preferences'] or 'none'}\n\n"
        "Rules:\n"
        "- silhouette_strategy: how to adapt the outfit to body proportions\n"
        "- palette_strategy: how to use preferred colors and harmonize them with appearance\n"
        "- outfit_focus: key garments and style emphasis for the event\n"
        "- footwear: most suitable shoe direction\n"
        "- accessories: fitting accessories direction\n"
        "- styling_notes: practical styling instructions for image generation\n"
        "- avoid: things that should be avoided based on the questionnaire\n"
        "- rationale: short explanation of why this styling direction fits the questionnaire\n"
        "Return concise but specific values."
    )

    raw = call_openrouter_text_model(
        OPENROUTER_ANALYSIS_MODEL,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return extract_json_object(raw)


def profile_number(profile: dict[str, str], field: str) -> float:
    number, _ = parse_questionnaire_number(profile.get(field), field)
    return number or 0


def determine_male_kibbe_archetype(profile: dict[str, str]) -> KibbeArchetype:
    height = profile_number(profile, "height")
    weight = profile_number(profile, "weight")
    bust = profile_number(profile, "bust")
    waist = profile_number(profile, "waist")
    hips = profile_number(profile, "hips")
    limb_length = profile.get("limb_length", "").lower()
    cheekbones = profile.get("cheekbones", "").lower()
    body_shape = profile.get("body_shape", "").lower()
    lip_size = profile.get("lip_size", "").lower()

    height_m = max(height / 100, 1)
    bmi = weight / (height_m * height_m)
    waist_gap = max((bust + hips) / 2, 1) - waist
    has_long_limbs = "длин" in limb_length
    has_short_limbs = "корот" in limb_length
    has_sharp_features = "ярко" in cheekbones or "узк" in lip_size
    has_soft_features = "мяг" in cheekbones or "пухл" in lip_size
    has_balanced_body = "симметр" in body_shape
    has_athletic_body = "спортив" in body_shape
    has_slim_body = "жилист" in body_shape or bmi < 21
    has_rounded_body = "округ" in body_shape or waist_gap >= 22

    if height >= 185 and has_slim_body and (has_long_limbs or has_sharp_features):
        key = "ДРАМАТИК"
    elif height >= 180 and (has_rounded_body or has_soft_features) and (has_long_limbs or has_sharp_features):
        key = "МЯГКИЙ ДРАМАТИК"
    elif height >= 175 and (has_athletic_body or has_long_limbs) and not has_soft_features:
        key = "НАТУРАЛ"
    elif 175 <= height <= 182 and (has_soft_features or has_rounded_body):
        key = "МЯГКИЙ НАТУРАЛ"
    elif 170 <= height <= 182 and has_balanced_body and not has_sharp_features and not has_rounded_body:
        key = "КЛАССИК"
    elif 172 <= height <= 182 and has_balanced_body and has_soft_features:
        key = "МЯГКИЙ КЛАССИК"
    elif 160 <= height <= 172 and (has_short_limbs or has_sharp_features) and not has_soft_features:
        key = "ЯРКИЙ ГАМИН"
    elif 162 <= height <= 175 and (has_short_limbs or has_soft_features) and has_rounded_body:
        key = "МЯГКИЙ ГАМИН"
    elif 170 <= height <= 180 and has_soft_features and has_rounded_body:
        key = "РОМАНТИК"
    elif 165 <= height <= 175 and has_soft_features and has_sharp_features:
        key = "ЯРКИЙ РОМАНТИК"
    elif height < 170:
        key = "МЯГКИЙ ГАМИН" if has_soft_features or has_rounded_body else "ЯРКИЙ ГАМИН"
    elif has_balanced_body:
        key = "КЛАССИК"
    else:
        key = "НАТУРАЛ"

    return KIBBE_ARCHETYPES[key]


def determine_kibbe_archetype(profile: dict[str, str]) -> KibbeArchetype:
    if profile.get("gender") == "Мужской":
        return determine_male_kibbe_archetype(profile)

    height = profile_number(profile, "height")
    weight = profile_number(profile, "weight")
    bust = profile_number(profile, "bust")
    waist = profile_number(profile, "waist")
    hips = profile_number(profile, "hips")
    limb_length = profile.get("limb_length", "").lower()
    cheekbones = profile.get("cheekbones", "").lower()
    body_shape = profile.get("body_shape", "").lower()
    lip_size = profile.get("lip_size", "").lower()

    avg_outer = max((bust + hips) / 2, 1)
    waist_gap = avg_outer - waist
    curve_ratio = waist_gap / avg_outer
    height_m = max(height / 100, 1)
    bmi = weight / (height_m * height_m)

    is_slim = bmi < 21 and bust <= 88 and hips <= 94
    is_curvy = curve_ratio >= 0.21 or (hips - waist >= 25 and bust - waist >= 20)
    is_straight = waist_gap <= 22
    is_compact = height <= 162
    is_moderate = 160 <= height <= 168
    has_long_limbs = "длин" in limb_length
    has_sharp_bone_structure = "ярко" in cheekbones
    has_soft_features = "мяг" in cheekbones or "пухл" in lip_size

    if "жилист" in body_shape:
        is_slim = True
        is_curvy = False
    elif "округ" in body_shape:
        is_curvy = True
        is_slim = False
    elif "спортив" in body_shape:
        is_straight = True
    elif "симметр" in body_shape:
        is_moderate = True

    if height >= 175 and is_slim and (has_long_limbs or has_sharp_bone_structure):
        key = "ДРАМАТИК"
    elif height >= 170 and is_curvy:
        key = "МЯГКИЙ ДРАМАТИК"
    elif 160 <= height <= 168 and is_slim and is_straight and has_sharp_bone_structure:
        key = "ЯРКИЙ ДРАМАТИК"
    elif height >= 170 and is_straight:
        key = "ЯРКИЙ НАТУРАЛ" if has_long_limbs or "спортив" in body_shape else "НАТУРАЛ"
    elif 160 <= height <= 166 and not is_curvy and (bust >= 88 or hips >= 94):
        key = "МЯГКИЙ НАТУРАЛ"
    elif 165 <= height <= 175 and is_straight:
        key = "ЯРКИЙ НАТУРАЛ"
    elif is_moderate and not is_curvy and not is_slim:
        key = "КЛАССИК"
    elif 160 <= height <= 166 and is_curvy and waist_gap <= 30:
        key = "МЯГКИЙ КЛАССИК"
    elif 155 <= height <= 162 and is_curvy and (bust >= 90 or hips >= 98):
        key = "РОМАНТИК"
    elif 150 <= height <= 157 and is_curvy and has_soft_features:
        key = "ЯРКИЙ РОМАНТИК"
    elif 155 <= height <= 164 and is_slim:
        key = "ГАМИН"
    elif 150 <= height <= 160 and is_curvy:
        key = "МЯГКИЙ ГАМИН"
    elif 155 <= height <= 160:
        key = "ЯРКИЙ ГАМИН"
    elif height >= 169:
        key = "НАТУРАЛ"
    elif is_compact:
        key = "МЯГКИЙ ГАМИН" if is_curvy else "ГАМИН"
    else:
        key = "КЛАССИК"

    return KIBBE_ARCHETYPES[key]


def kibbe_clothing_for_profile(profile: dict[str, str], kibbe: KibbeArchetype) -> str:
    if profile["gender"] != "Мужской":
        return kibbe.clothing

    menswear_by_archetype = {
        "ДРАМАТИК": "elongated sharp menswear silhouette, long straight coats, straight trousers, monochrome or graphic blocks, dense smooth fabrics, very few soft details",
        "МЯГКИЙ ДРАМАТИК": "elongated menswear silhouette with broad rounded details, long coats, straight trousers, dense fabrics, large smooth accents, controlled waist-aware layering",
        "ЯРКИЙ ДРАМАТИК": "compact sharp menswear, cropped structured jackets, graphic contrast, slim or straight trousers, clean angular details",
        "НАТУРАЛ": "relaxed masculine width, unstructured jackets, loose straight trousers, mixed casual layers, rough natural textures, broad simple details",
        "МЯГКИЙ НАТУРАЛ": "soft relaxed menswear, loose trousers and jackets, rounded flexible details, lively colors or soft prints, textured soft natural fabrics",
        "ЯРКИЙ НАТУРАЛ": "long relaxed menswear lines, oversized coats, wide trousers, chunky textures, large-scale casual tailoring",
        "КЛАССИК": "balanced menswear classics, slightly elongated clean silhouette, precise trousers and jackets, symmetrical collars and cuffs, minimal excess detail",
        "МЯГКИЙ КЛАССИК": "restrained soft classic menswear, ideal-fit jackets and coats, slightly tapered trousers, rounded smooth details, high-quality soft fabrics",
        "РОМАНТИК": "soft masculine styling with subtle waist suggestion, rounded collars, fluid knitwear or shirts, supple fabrics, compact proportion, no feminine dresses",
        "ЯРКИЙ РОМАНТИК": "compact expressive menswear, fitted short jackets, soft shirts, deep contrast, small refined accessories, waist-aware silhouette",
        "ГАМИН": "compact energetic menswear, cropped jackets, graphic separates, contrast top and trousers, sharp small accessories",
        "МЯГКИЙ ГАМИН": "compact soft menswear, short jackets, fitted jumpers, narrow trousers, playful masculine accents, clear silhouette and flexible fabrics",
        "ЯРКИЙ ГАМИН": "compact expressive menswear, firm cropped jackets, straight or cropped trousers, bright contrast blocks, structured fabrics, bold masculine details",
    }
    return menswear_by_archetype.get(kibbe.name, "masculine menswear adapted to the Kibbe silhouette")


def build_body_visual_description(profile: dict[str, str]) -> str:
    height = profile_number(profile, "height")
    weight = profile_number(profile, "weight")
    bust = profile_number(profile, "bust")
    waist = profile_number(profile, "waist")
    hips = profile_number(profile, "hips")
    height_m = max(height / 100, 1)
    bmi = weight / (height_m * height_m)
    avg_outer = max((bust + hips) / 2, 1)
    waist_gap = avg_outer - waist

    body_shape_value = profile.get("body_shape", "")
    if body_shape_value == "Округлое пышное":
        build = "fuller soft rounded silhouette with visible volume, softer torso, fuller upper and lower proportions"
    elif body_shape_value == "Спортивное мускулинное":
        build = "athletic muscular build with visible muscle structure"
    elif body_shape_value == "Жилистое худое":
        build = "lean wiry thin build with dry narrow lines"
    elif body_shape_value == "Симметричное пропорциональное":
        build = "balanced proportional medium build"
    elif bmi < 19:
        build = "slim, lightweight build"
    elif bmi < 24:
        build = "balanced medium build"
    elif bmi < 29:
        build = "solid medium build"
    else:
        build = "fuller strong build"

    if height >= 185:
        height_note = "very tall vertical line"
    elif height >= 175:
        height_note = "tall vertical line"
    elif height <= 162:
        height_note = "compact height"
    else:
        height_note = "moderate height"

    if waist_gap >= 26:
        proportion_note = "visible waist definition compared with chest and hips"
    elif waist_gap <= 14:
        proportion_note = "straighter torso with little waist contrast"
    else:
        proportion_note = "moderate waist shaping"

    gender_note = (
        "male fashion silhouette, masculine torso and shoulders"
        if profile["gender"] == "Мужской"
        else "female fashion silhouette with the questionnaire proportions"
    )
    limb_map = {
        "Длинные": "long limbs relative to torso",
        "Пропорциональные": "proportional limbs relative to torso",
        "Коротковатые": "slightly short limbs relative to torso",
    }
    body_shape_map = {
        "Жилистое худое": "lean wiry thin body shape",
        "Симметричное пропорциональное": "symmetrical proportional body shape",
        "Округлое пышное": "rounded full body shape",
        "Спортивное мускулинное": "athletic muscular body shape",
    }
    cheekbone_map = {
        "Ярко выраженные подтянутые": "sharp prominent lifted cheekbones",
        "Мягкие": "soft cheekbones",
        "Невыраженные": "subtle low-contrast cheekbones",
    }
    lip_map = {
        "Узкие": "low facial softness",
        "Средние": "medium facial softness",
        "Пухлые": "high facial softness",
    }
    return (
        f"Visual body target: {gender_note}; {height_note}; {build}; "
        f"{proportion_note}; upper measurement {bust:g} cm, waist {waist:g} cm, lower measurement {hips:g} cm. "
        f"Limbs relative to torso: {limb_map.get(profile.get('limb_length', ''), 'not specified')}. "
        f"Body shape: {body_shape_map.get(profile.get('body_shape', ''), 'not specified')}. "
        f"Cheekbones: {cheekbone_map.get(profile.get('cheekbones', ''), 'not specified')}. "
        f"Facial softness: {lip_map.get(profile.get('lip_size', ''), 'not specified')}. "
        "The model body must visually reflect these measurements instead of a generic fashion-model body."
    )


def build_safe_image_body_description(profile: dict[str, str]) -> str:
    """Less sensitive body guidance for image safety filters."""
    height = profile_number(profile, "height")
    weight = profile_number(profile, "weight")
    height_m = max(height / 100, 1)
    bmi = weight / (height_m * height_m)

    if height >= 185:
        height_note = "very tall vertical proportion"
    elif height >= 175:
        height_note = "tall vertical proportion"
    elif height <= 162:
        height_note = "compact vertical proportion"
    else:
        height_note = "moderate vertical proportion"

    body_shape_map = {
        "Жилистое худое": "lean wiry narrow frame",
        "Симметричное пропорциональное": "balanced proportional medium frame",
        "Округлое пышное": "soft rounded fuller frame with gentle volume",
        "Спортивное мускулинное": "athletic structured frame",
    }
    build = body_shape_map.get(profile.get("body_shape", ""))
    if not build:
        if bmi < 19:
            build = "slim lightweight frame"
        elif bmi < 24:
            build = "balanced medium frame"
        elif bmi < 29:
            build = "solid medium frame"
        else:
            build = "fuller strong frame"

    limb_map = {
        "Длинные": "long limbs relative to torso",
        "Пропорциональные": "balanced limbs relative to torso",
        "Коротковатые": "slightly shorter limbs relative to torso",
    }
    cheekbone_map = {
        "Ярко выраженные подтянутые": "defined cheekbone impression",
        "Мягкие": "soft facial impression",
        "Невыраженные": "low-contrast facial impression",
    }
    gender_note = "masculine styling base" if profile["gender"] == "Мужской" else "feminine styling base"
    return (
        f"Safe fit profile for clothing only: {gender_note}; {height_note}; {build}; "
        f"{limb_map.get(profile.get('limb_length', ''), 'balanced limbs')}; "
        f"{cheekbone_map.get(profile.get('cheekbones', ''), 'balanced facial impression')}. "
        "Use these cues only to choose garment length, layering volume, waist placement, and silhouette. "
        "Keep the pose neutral, fully clothed, editorial, and focused on garments."
    )


def build_image_age_line(profile: dict[str, str]) -> str:
    age = profile_number(profile, "age")
    if age < 18:
        return (
            "age-neutral youthful fashion model, clean-shaven if male, no beard, "
            "no mature adult facial hair, face cropped or de-emphasized, outfit-focused"
        )
    return f"adult model age {int(age)}"


def build_body_shape_lock(profile: dict[str, str]) -> str:
    body_shape = profile.get("body_shape", "")
    locks = {
        "Округлое пышное": (
            "STRICT BODY SHAPE: rounded full body, plus-size or fuller soft build, visible body volume, "
            "soft waist and torso, fuller upper and lower silhouette. Do NOT make the model lean, skinny, dry, athletic, muscular, six-pack, or fitness-model shaped. "
            "If the occasion is sport, keep only the CLOTHES sporty; the BODY must still be rounded and full."
        ),
        "Спортивное мускулинное": (
            "STRICT BODY SHAPE: athletic muscular body with visible structure, broader shoulders, trained torso, energetic posture."
        ),
        "Жилистое худое": (
            "STRICT BODY SHAPE: lean wiry thin body, narrow dry lines, lightweight frame, not bulky or rounded."
        ),
        "Симметричное пропорциональное": (
            "STRICT BODY SHAPE: balanced proportional body, medium frame, neither very thin nor plus-size nor extremely muscular."
        ),
    }
    return locks.get(body_shape, "")


def event_matches(event: str, *needles: str) -> bool:
    return any(needle in event for needle in needles)


def resolve_event_style(profile: dict[str, str]) -> EventStyleBrief:
    event = profile["event"].lower()
    is_male = profile["gender"] == "Мужской"

    if event_matches(event, "офис", "делов", "работ", "собесед", "переговор", "конференц", "презентац"):
        outfit = (
            "office/business: tailored jacket or overshirt, shirt or fine knit, tailored trousers, loafers or derby shoes"
            if is_male
            else "office/business: blazer, tailored trousers or skirt, blouse or fine knit, refined shoes"
        )
        footwear = "loafers, derby shoes, or minimal leather sneakers" if is_male else "loafers, pumps, or refined ankle boots"
        accessories = "clean belt, watch, structured leather bag" if is_male else "structured bag, delicate jewelry, clean belt"
        avoid = "avoid streetwear that looks too casual for a business meeting"
        scene = "business-casual editorial studio, calm confident pose"
        category = "business"
    elif event_matches(event, "свидан", "ресторан", "ужин", "кафе", "кино"):
        outfit = (
            "date: knit polo, relaxed open-collar shirt, suede jacket or textured overshirt, clean denim or relaxed trousers"
            if is_male
            else "date: flattering dress or soft separates, refined layers, elegant but comfortable shoes"
        )
        footwear = "loafers, suede shoes, Chelsea boots, or clean low-profile sneakers" if is_male else "elegant heels, ballet flats, or refined boots"
        accessories = "watch, leather belt, compact crossbody or tote" if is_male else "small shoulder bag, subtle jewelry, soft glow makeup"
        avoid = "avoid a strict office suit, tie, boardroom styling, or corporate uniform"
        scene = "warm evening city or cafe-inspired fashion photo"
        category = "date"
    elif event_matches(event, "вечерин", "вечерний выход", "вечернее мероприят", "клуб", "бар", "день рожд", "праздник"):
        outfit = (
            "party/evening: expressive dark menswear, textured shirt or knit, statement jacket or leather layer, polished trousers"
            if is_male
            else "party/evening: expressive dress or elevated separates, refined shine, evening shoes"
        )
        footwear = "Chelsea boots, polished loafers, or sleek sneakers" if is_male else "fashion heels, sleek boots, or dressy flats"
        accessories = "minimal jewelry, watch, clean belt" if is_male else "statement earrings, compact clutch, metallic details"
        avoid = "avoid daytime office uniform and generic business-casual styling"
        scene = "night-out editorial lighting, modern event atmosphere"
        category = "party"
    elif event_matches(event, "спорт", "зал", "трениров", "фитнес", "пробеж", "йога"):
        outfit = (
            "athleisure: technical t-shirt or hoodie, track jacket, relaxed joggers or performance trousers, sporty layers"
            if is_male
            else "athleisure: technical top, hoodie or cropped jacket, leggings or joggers, sporty layers"
        )
        footwear = "modern sneakers only"
        accessories = "minimal sport watch, small crossbody or gym bag"
        avoid = "avoid formal shirts, blazers, suits, ties, dress shoes, and office trousers"
        scene = "clean athletic lifestyle photo, urban sport background"
        category = "sport"
    elif event_matches(event, "учеб", "универ", "колледж", "школ", "лекц", "кампус"):
        outfit = (
            "campus casual: relaxed overshirt, knit or hoodie, straight jeans or chinos, layered practical outerwear"
            if is_male
            else "campus casual: knitwear, overshirt or jacket, jeans or relaxed trousers/skirt, practical stylish layers"
        )
        footwear = "comfortable sneakers, loafers, or casual boots"
        accessories = "backpack, tote, watch, simple accessories"
        avoid = "avoid corporate suits, ties, evening wear, and overly formal office styling"
        scene = "campus or city-daylight lifestyle fashion photo"
        category = "campus"
    elif event_matches(event, "свад", "церемон", "торже", "выпуск", "банкет"):
        outfit = (
            "formal celebration: elegant suit separates or refined jacket, dress shirt without corporate stiffness, festive texture"
            if is_male
            else "formal celebration: elegant dress or refined evening separates, festive texture and graceful silhouette"
        )
        footwear = "polished loafers, derby shoes, or elegant boots" if is_male else "heels, elegant flats, or refined sandals"
        accessories = "watch, pocket square or subtle jewelry, clean belt" if is_male else "clutch, jewelry, polished evening details"
        avoid = "avoid casual streetwear, gym clothes, and everyday denim"
        scene = "formal celebration editorial, soft elegant lighting"
        category = "formal"
    elif event_matches(event, "пляж", "море", "курорт", "отпуск", "жара", "лето"):
        outfit = (
            "resort casual: linen shirt, relaxed trousers or tailored shorts, light overshirt, breathable fabrics"
            if is_male
            else "resort casual: linen dress or breathable separates, relaxed layers, light natural fabrics"
        )
        footwear = "sandals, espadrilles, or clean summer sneakers"
        accessories = "sunglasses, woven bag or tote, minimal jewelry"
        avoid = "avoid office suits, ties, heavy coats, and stiff corporate shoes"
        scene = "warm resort or summer city fashion photo"
        category = "resort"
    elif event_matches(event, "путеше", "weekend", "выходн", "поезд", "аэропорт"):
        outfit = (
            "travel/weekend: relaxed practical menswear, chore jacket or bomber, knit or t-shirt, loose trousers or quality denim"
            if is_male
            else "travel/weekend: relaxed practical layers, knitwear, denim or soft trousers, comfortable stylish shoes"
        )
        footwear = "comfortable sneakers, loafers, or casual boots"
        accessories = "crossbody bag, sunglasses, practical outer layer"
        avoid = "avoid formal office suits, ties, stiff dress shoes, and evening-only outfits"
        scene = "travel lifestyle photo, relaxed movement, natural daylight"
        category = "travel"
    elif event_matches(event, "творчес", "выстав", "галере", "театр", "концерт", "фото", "арт"):
        outfit = (
            "creative event: artistic masculine layering, textured jacket, interesting shirt or knit, wider trousers, boots or designer sneakers"
            if is_male
            else "creative event: artistic layers, interesting textures, expressive silhouette, modern shoes"
        )
        footwear = "designer sneakers, boots, or expressive loafers"
        accessories = "statement but minimal accessory, tote or crossbody, watch"
        avoid = "avoid conservative corporate styling and generic office looks"
        scene = "gallery-inspired fashion photo, artful background, not office"
        category = "creative"
    elif event_matches(event, "повседнев", "город", "прогул", "друз", "магаз", "парк"):
        outfit = (
            "everyday city: casual menswear, t-shirt or knit, overshirt/chore jacket/bomber, denim or relaxed trousers"
            if is_male
            else "everyday city: modern casual layers, knitwear, denim or relaxed trousers/skirt, comfortable stylish shoes"
        )
        footwear = "sneakers, casual loafers, or relaxed boots"
        accessories = "crossbody bag, cap or sunglasses if appropriate, watch"
        avoid = "avoid formal suit, tie, strict office blazer, and ceremonial clothing"
        scene = "realistic city street-style photo, daylight, relaxed pose"
        category = "casual"
    else:
        outfit = (
            f"non-business outfit for this exact user-written occasion: {profile['event']}; use relaxed real menswear unless the event explicitly says business"
            if is_male
            else f"outfit for this exact user-written occasion: {profile['event']}; use wearable real clothes, not office wear unless explicitly requested"
        )
        footwear = "shoes that match the user's written occasion"
        accessories = "small accessories that match the user's written occasion"
        avoid = "avoid generic office suits, ties, corporate styling, and any outfit that ignores the written occasion"
        scene = "realistic lifestyle fashion photo matching the written occasion"
        category = "custom"

    return EventStyleBrief(
        category=category,
        outfit=outfit,
        footwear=footwear,
        accessories=accessories,
        avoid=avoid,
        scene=scene,
    )


def build_event_outfit_rules(profile: dict[str, str]) -> str:
    brief = safe_event_for_generation(profile, resolve_event_style(profile))
    return (
        f"Event category: {brief.category}. Mandatory outfit category: {brief.outfit}. "
        f"Mandatory footwear: {brief.footwear}. Strict event mismatch rule: {brief.avoid}."
    )


def build_event_variation_style(profile: dict[str, str], index: int) -> str:
    category = safe_event_for_generation(profile, resolve_event_style(profile)).category
    is_male = profile["gender"] == "Мужской"
    male_variations = {
        "casual": [
            "plain heavyweight t-shirt, relaxed pleated trousers, casual leather crossbody",
            "textured knit polo, straight denim, lightweight bomber jacket",
            "overshirt over clean tee, loose chinos, minimal sneakers",
            "linen shirt worn open over tank or tee, relaxed trousers",
            "soft cardigan, clean t-shirt, dark denim, casual loafers",
        ],
        "date": [
            "knit polo, relaxed trousers, suede loafers",
            "open-collar shirt, clean denim, textured jacket",
            "fine knit top, wide trousers, Chelsea boots",
            "soft overshirt, monochrome tee, straight trousers",
        ],
        "sport": [
            "technical t-shirt, track jacket, joggers, modern sneakers",
            "hoodie, performance trousers, minimal gym bag",
            "zip sweatshirt, athletic shorts or joggers, running sneakers",
        ],
        "campus": [
            "hoodie under overshirt, straight jeans, sneakers, backpack",
            "knit sweater, relaxed chinos, casual jacket",
            "graphic-free t-shirt, bomber jacket, loose denim",
        ],
        "business": [
            "unstructured blazer, fine knit, tailored trousers",
            "clean shirt, soft jacket, loafers",
            "minimal overshirt, pressed trousers, leather shoes",
        ],
        "party": [
            "dark textured shirt, statement jacket, slim-straight trousers",
            "monochrome knit, leather jacket, polished boots",
            "open-collar shirt, dark trousers, expressive outer layer",
        ],
        "youth_social": [
            "clean statement hoodie, relaxed trousers, stylish sneakers, compact crossbody",
            "graphic-free overshirt, comfortable tee, loose denim, modern sneakers",
            "soft knit layer, relaxed cargo-style trousers, safe evening casual accessories",
        ],
        "formal": [
            "celebration suit separates, soft dress shirt, polished loafers",
            "refined jacket, elegant trousers, festive texture",
        ],
        "resort": [
            "linen shirt, relaxed trousers, sandals or espadrilles",
            "light overshirt, breathable tee, tailored shorts",
        ],
        "travel": [
            "chore jacket, t-shirt, loose trousers, sneakers",
            "bomber jacket, knit, quality denim, crossbody bag",
        ],
        "creative": [
            "textured jacket, artistic shirt, wide trousers, boots",
            "layered overshirt, interesting knit, designer sneakers",
        ],
        "custom": [
            "non-business outfit that exactly matches the written occasion",
            "relaxed real-world outfit with no corporate suit unless requested",
        ],
    }
    female_variations = {
        "casual": [
            "knit top, relaxed jeans, overshirt or soft jacket",
            "simple dress with casual outer layer and comfortable shoes",
            "cardigan, clean top, relaxed trousers",
        ],
        "date": [
            "soft dress or blouse with relaxed skirt/trousers",
            "elegant knit, flattering trousers, refined shoes",
        ],
        "sport": [
            "technical top, hoodie, joggers or leggings, modern sneakers",
            "zip jacket, athletic set, practical gym bag",
        ],
        "business": [
            "soft blazer, blouse or knit, tailored trousers or skirt",
            "minimal suit separates with refined shoes",
        ],
        "party": [
            "expressive evening dress or elevated separates",
            "sleek top, statement skirt or trousers, evening shoes",
        ],
        "youth_social": [
            "modest stylish top, relaxed skirt or trousers, comfortable sneakers",
            "soft hoodie or zip jacket, relaxed trousers, practical small bag",
            "layered knit, midi skirt or loose trousers, flat boots or sneakers",
        ],
        "custom": [
            "wearable outfit that exactly matches the written occasion",
        ],
    }
    fallback = male_variations if is_male else female_variations
    options = fallback.get(category) or fallback.get("custom") or ["occasion-matched outfit"]
    outfit = options[(index - 1) % len(options)]
    if is_male and user_requested_nonstandard_garment(
        profile,
        "юбк",
        "юпк",
        "skirt",
        "килт",
        "kilt",
    ):
        if category == "sport":
            outfit = "technical top, track jacket or hoodie, user-requested masculine sport skirt or kilt-inspired skirt over compression shorts, modern sneakers"
        else:
            outfit += ", replacing trousers with the user-requested masculine skirt or kilt-inspired skirt as the main lower garment"
    elif is_male and user_requested_nonstandard_garment(profile, "плать", "dress"):
        outfit += ", with the user-requested dress-like long tunic or dress silhouette integrated into male fashion styling"
    return outfit


EVENT_CATEGORY_LABELS_RU = {
    "business": "деловой",
    "date": "свидание",
    "party": "вечерний выход",
    "youth_social": "молодёжный вечер",
    "sport": "спорт",
    "campus": "учёба",
    "formal": "торжество",
    "resort": "курорт",
    "travel": "поездка",
    "creative": "творческое событие",
    "casual": "повседневный",
    "custom": "индивидуальный повод",
}


def event_category_label_ru(category: str) -> str:
    return EVENT_CATEGORY_LABELS_RU.get(category, "персональный сценарий")


def build_event_variation_style_ru(profile: dict[str, str], index: int) -> str:
    category = safe_event_for_generation(profile, resolve_event_style(profile)).category
    is_male = profile["gender"] == "Мужской"
    male_variations = {
        "casual": [
            "плотная базовая футболка, свободные брюки со складками, кожаная сумка через плечо",
            "фактурное трикотажное поло, прямой деним, лёгкий бомбер",
            "верхняя рубашка поверх чистой футболки, свободные чиносы, минималистичные кроссовки",
            "льняная рубашка поверх базового слоя, расслабленные брюки",
            "мягкий кардиган, чистая футболка, тёмный деним, casual-лоферы",
        ],
        "date": [
            "трикотажное поло, расслабленные брюки, замшевые лоферы",
            "рубашка с открытым воротом, чистый деним, фактурная куртка",
            "тонкий трикотаж, широкие брюки, челси",
            "мягкая верхняя рубашка, монохромная футболка, прямые брюки",
        ],
        "sport": [
            "техническая футболка, спортивная куртка, джоггеры, современные кроссовки",
            "худи, функциональные брюки, минималистичная спортивная сумка",
            "свитшот на молнии, спортивные шорты или джоггеры, беговые кроссовки",
        ],
        "campus": [
            "худи под верхней рубашкой, прямые джинсы, кроссовки, рюкзак",
            "трикотажный свитер, свободные чиносы, casual-куртка",
            "футболка без принта, бомбер, свободный деним",
        ],
        "business": [
            "мягкий пиджак без жёсткой конструкции, тонкий трикотаж, аккуратные брюки",
            "чистая рубашка, мягкий жакет, лоферы",
            "минималистичная верхняя рубашка, отглаженные брюки, кожаная обувь",
        ],
        "party": [
            "тёмная фактурная рубашка, акцентный жакет, прямые брюки",
            "монохромный трикотаж, кожаный слой, аккуратные ботинки",
            "рубашка с открытым воротом, тёмные брюки, выразительный верхний слой",
        ],
        "youth_social": [
            "акцентное худи без агрессивного принта, свободные брюки, стильные кроссовки, компактная сумка",
            "верхняя рубашка без принта, удобная футболка, свободный деним, современные кроссовки",
            "мягкий трикотажный слой, relaxed cargo-брюки, безопасные вечерние casual-аксессуары",
        ],
        "formal": [
            "праздничные костюмные элементы, мягкая сорочка, полированные лоферы",
            "утончённый жакет, элегантные брюки, праздничная фактура",
        ],
        "resort": [
            "льняная рубашка, свободные брюки, сандалии или эспадрильи",
            "лёгкая верхняя рубашка, дышащая футболка, аккуратные шорты",
        ],
        "travel": [
            "рабочая куртка, футболка, свободные брюки, кроссовки",
            "бомбер, трикотаж, качественный деним, сумка через плечо",
        ],
        "creative": [
            "фактурный жакет, артистичная рубашка, широкие брюки, ботинки",
            "многослойная верхняя рубашка, интересный трикотаж, дизайнерские кроссовки",
        ],
        "custom": [
            "неформальный комплект, точно подстроенный под указанный повод",
            "реалистичный расслабленный образ без офисного костюма, если он не был запрошен",
        ],
    }
    female_variations = {
        "casual": [
            "трикотажный топ, расслабленные джинсы, верхняя рубашка или мягкий жакет",
            "простое платье с casual-слоем и удобной обувью",
            "кардиган, чистый топ, расслабленные брюки",
        ],
        "date": [
            "мягкое платье или блуза с расслабленной юбкой либо брюками",
            "элегантный трикотаж, комплиментарные брюки, утончённая обувь",
        ],
        "sport": [
            "технический топ, худи, джоггеры или легинсы, современные кроссовки",
            "куртка на молнии, спортивный комплект, практичная сумка",
        ],
        "business": [
            "мягкий жакет, блуза или трикотаж, аккуратные брюки либо юбка",
            "минималистичные костюмные элементы с утончённой обувью",
        ],
        "party": [
            "выразительное вечернее платье или elevated separates",
            "лаконичный топ, акцентная юбка или брюки, вечерняя обувь",
        ],
        "youth_social": [
            "сдержанный стильный верх, расслабленная юбка или брюки, удобные кроссовки",
            "мягкое худи или куртка на молнии, relaxed-брюки, практичная небольшая сумка",
            "многослойный трикотаж, миди-юбка или свободные брюки, плоские ботинки или кроссовки",
        ],
        "custom": [
            "носибельный комплект, точно подстроенный под указанный повод",
        ],
    }
    fallback = male_variations if is_male else female_variations
    options = fallback.get(category) or fallback.get("custom") or ["образ под выбранный повод"]
    outfit = options[(index - 1) % len(options)]
    if is_male and user_requested_nonstandard_garment(profile, "юбк", "юпк", "skirt", "килт", "kilt"):
        outfit += ", с учётом запрошенной мужской юбки или kilt-inspired нижней части"
    elif is_male and user_requested_nonstandard_garment(profile, "плать", "dress"):
        outfit += ", с учётом запрошенного длинного туникообразного или dress-like силуэта"
    return outfit


def build_event_look_title(profile: dict[str, str], index: int) -> str:
    category = safe_event_for_generation(profile, resolve_event_style(profile)).category
    titles = {
        "business": [
            "Деловой баланс",
            "Мягкий офисный силуэт",
            "Деловой casual",
            "Собранная встреча",
        ],
        "date": [
            "Образ для свидания",
            "Вечерняя мягкость",
            "Кафе и прогулка",
            "Спокойная привлекательность",
        ],
        "party": [
            "Вечерний акцент",
            "Вечерняя фактура",
            "Ночной силуэт",
            "Выразительный выход",
        ],
        "youth_social": [
            "Вечерний casual",
            "Молодёжный выход",
            "Музыкальный ритм",
            "Свободный вечер",
        ],
        "sport": [
            "Спортивный casual",
            "Спортивный ритм",
            "Тренировка и город",
            "Динамичный комплект",
        ],
        "campus": [
            "Кампус casual",
            "Учебный день",
            "Расслабленный кампус",
            "Удобный городской слой",
        ],
        "formal": [
            "Торжественный образ",
            "Праздничный комплект",
            "Мягкая формальность",
            "Праздничная линия",
        ],
        "resort": [
            "Курортный casual",
            "Летняя лёгкость",
            "Курортная линия",
            "Свободный лен",
        ],
        "travel": [
            "Слои для поездки",
            "Образ выходного дня",
            "Образ для поездки",
            "Свободное движение",
        ],
        "creative": [
            "Творческая многослойность",
            "Галерейный образ",
            "Арт-силуэт",
            "Фактурный акцент",
        ],
        "casual": [
            "Городской casual",
            "Прогулочный образ",
            "Спокойный город",
            "Повседневный стиль",
        ],
        "custom": [
            "Образ под событие",
            "Персональный комплект",
            "Индивидуальный образ",
            "Сценарный образ",
        ],
    }
    options = titles.get(category) or titles["custom"]
    return options[(index - 1) % len(options)]


def build_display_reason_ru(
    profile: dict[str, str],
    index: int,
    kibbe_name: str,
    analysis: dict[str, Any],
) -> str:
    event_style = safe_event_for_generation(profile, resolve_event_style(profile))
    kibbe_line = str(analysis.get("kibbe_line", "")).strip()
    line_note = f" Линия Кибби: {kibbe_line}." if kibbe_line else ""
    return (
        f"AI подготовил образ #{index} под событие «{profile['event']}» "
        f"в категории «{event_category_label_ru(event_style.category)}», с опорой на архетип Кибби "
        f"«{kibbe_name}», выбранную палитру «{profile['preferred_colors']}» и параметры анкеты."
        f"{line_note}"
    )


def build_display_note_ru(
    profile: dict[str, str],
    index: int,
    direction: LookDirection,
    analysis: dict[str, Any],
) -> str:
    event_style = safe_event_for_generation(profile, resolve_event_style(profile))
    return (
        f"{event_category_label_ru(event_style.category)} • {direction.vibe}. "
        f"Одежда под событие: {build_event_variation_style_ru(profile, index)}. "
        f"Линия Кибби: {analysis.get('kibbe_line', '')}."
    )


LEGACY_TITLE_TRANSLATIONS = {
    "Business Casual": "Деловой casual",
    "Party Texture": "Вечерняя фактура",
    "Athleisure": "Спортивный casual",
    "Campus Casual": "Кампус casual",
    "Celebration Look": "Праздничный комплект",
    "Resort Casual": "Курортный casual",
    "Travel Layering": "Слои для поездки",
    "Weekend Look": "Образ выходного дня",
    "Creative Layering": "Творческая многослойность",
    "Relaxed City": "Спокойный город",
    "Individual look": "Индивидуальный образ",
}


LEGACY_TEXT_REPLACEMENTS = {
    "casual": "повседневный",
    "business": "деловой",
    "sport": "спорт",
    "party": "вечерний выход",
    "campus": "учёба",
    "formal": "торжество",
    "resort": "курорт",
    "travel": "поездка",
    "creative": "творческое событие",
    "custom": "индивидуальный повод",
    "plain heavyweight t-shirt, relaxed pleated trousers, casual leather crossbody": "плотная базовая футболка, свободные брюки со складками, кожаная сумка через плечо",
    "textured knit polo, straight denim, lightweight bomber jacket": "фактурное трикотажное поло, прямой деним, лёгкий бомбер",
    "overshirt over clean tee, loose chinos, minimal sneakers": "верхняя рубашка поверх чистой футболки, свободные чиносы, минималистичные кроссовки",
    "knit polo, relaxed trousers, suede loafers": "трикотажное поло, расслабленные брюки, замшевые лоферы",
    "technical t-shirt, track jacket, joggers, modern sneakers": "техническая футболка, спортивная куртка, джоггеры, современные кроссовки",
    "hoodie, performance trousers, minimal gym bag": "худи, функциональные брюки, минималистичная спортивная сумка",
    "zip sweatshirt, athletic shorts or joggers, running sneakers": "свитшот на молнии, спортивные шорты или джоггеры, беговые кроссовки",
    "the outfit follows": "образ следует",
    "fits the event": "подходит под событие",
    "uses the requested colors": "использует выбранные цвета",
    "respects the provided body measurements": "учитывает параметры анкеты",
}


def localize_legacy_text(value: str) -> str:
    localized = value
    if "the outfit follows" in localized.lower() or "fits the event" in localized.lower():
        return (
            "Образ подготовлен под выбранное событие, палитру и архетип Кибби. "
            "Силуэт, посадка и степень формальности рассчитаны по параметрам анкеты."
        )
    for source, target in LEGACY_TEXT_REPLACEMENTS.items():
        localized = re.sub(rf"\b{re.escape(source)}\b", target, localized, flags=re.IGNORECASE)
    return localized


def localize_saved_look(look: dict[str, Any]) -> dict[str, Any]:
    localized = dict(look)
    title = str(localized.get("title", ""))
    localized["title"] = LEGACY_TITLE_TRANSLATIONS.get(title, title)
    for key in ("vibe", "note", "reason"):
        if key in localized and isinstance(localized[key], str):
            localized[key] = localize_legacy_text(localized[key])
    return localized


def build_local_style_brief(profile: dict[str, str]) -> dict[str, Any]:
    colors = profile["preferred_colors"].lower()
    mood = profile["style_goals"].lower()
    kibbe = determine_kibbe_archetype(profile)
    kibbe_clothing = kibbe_clothing_for_profile(profile, kibbe)
    event_style = safe_event_for_generation(profile, resolve_event_style(profile))
    silhouette = f"{kibbe.line}; adapt the event outfit to this Kibbe line and the user's measurements"
    outfit = event_style.outfit
    footwear = event_style.footwear
    accessories = event_style.accessories

    if "ярк" in colors or "неон" in colors:
        palette = "use the requested colors as accent points, balance them with deep neutrals"
    elif "чёр" in colors or "черн" in colors:
        palette = "center the palette around black and deep contrast neutrals with one soft highlight"
    elif "молоч" in colors or "беж" in colors:
        palette = "use a soft light palette with warm neutrals and one muted accent"
    else:
        palette = "harmonize the requested colors with the person's appearance, keeping the result premium and wearable"

    return {
        "kibbe_archetype": kibbe.name,
        "kibbe_line": kibbe.line,
        "kibbe_clothing": kibbe_clothing,
        "kibbe_avoid": kibbe.avoid,
        "silhouette_strategy": silhouette,
        "palette_strategy": palette,
        "outfit_focus": f"{outfit}. Kibbe clothing direction: {kibbe_clothing}",
        "footwear": footwear,
        "accessories": accessories,
        "styling_notes": (
            f"Kibbe archetype: {kibbe.name}. Body-aware styling for {profile['gender'].lower()} body type, "
            f"measurements {profile['bust']}/{profile['waist']}/{profile['hips']}, "
            f"limbs: {profile.get('limb_length', '')}, body shape: {profile.get('body_shape', '')}, "
            f"cheekbones: {profile.get('cheekbones', '')}, lips: {profile.get('lip_size', '')}, "
            f"hair texture: {profile.get('hair_texture', '')}, "
            f"preferred mood: {mood or 'balanced'}. "
            "Keep the look realistic, editorial, and wearable."
        ),
        "event_category": event_style.category,
        "event_scene": event_style.scene,
        "event_avoid": event_style.avoid,
        "avoid": f"{kibbe.avoid}; {event_style.avoid}; overly busy prints, mismatched proportions, generic styling, and anything that clashes with the event",
        "rationale": (
            f"The outfit follows the {kibbe.name} Kibbe archetype, fits the event '{profile['event']}', "
            f"uses the requested colors '{profile['preferred_colors']}', and respects the provided body measurements."
        ),
    }


def analyze_profile_free(profile: dict[str, str]) -> dict[str, Any]:
    return build_local_style_brief(profile)


def resolve_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
    if bold:
        bold_candidate = Path(path).with_name("DejaVuSans-Bold.ttf")
        if bold_candidate.exists():
            path = str(bold_candidate)
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def parse_color_token(token: str) -> tuple[int, int, int] | None:
    token = token.lower().strip()
    palette_map = {
        "черн": (17, 17, 24),
        "чёрн": (17, 17, 24),
        "black": (17, 17, 24),
        "молоч": (246, 239, 227),
        "бел": (250, 250, 248),
        "white": (250, 250, 248),
        "лаванд": (180, 146, 255),
        "лилов": (195, 144, 255),
        "фиолет": (129, 84, 245),
        "пурпур": (177, 98, 204),
        "пастел": (227, 196, 233),
        "розов": (242, 173, 202),
        "пудр": (227, 181, 198),
        "беж": (218, 198, 173),
        "сер": (153, 160, 179),
        "син": (80, 116, 223),
        "голуб": (124, 197, 242),
        "зел": (74, 156, 123),
        "изумруд": (26, 121, 104),
        "красн": (202, 68, 72),
        "вин": (121, 32, 61),
        "бордо": (121, 32, 61),
        "корич": (138, 91, 59),
        "карам": (188, 137, 83),
        "золот": (199, 166, 79),
        "сереб": (193, 201, 219),
    }
    for key, value in palette_map.items():
        if key in token:
            return value
    return None


def translate_color_preferences(value: str) -> list[str]:
    color_map = {
        "черн": "black",
        "чёрн": "black",
        "black": "black",
        "молоч": "milk white",
        "бел": "pure white",
        "white": "pure white",
        "лаванд": "lavender",
        "лилов": "lilac",
        "фиолет": "violet purple",
        "пурпур": "purple",
        "пастел": "pastel",
        "розов": "soft pink",
        "пудр": "powder pink",
        "беж": "beige",
        "сер": "grey",
        "син": "blue",
        "голуб": "light blue",
        "зел": "green",
        "изумруд": "emerald green",
        "красн": "red",
        "вин": "burgundy",
        "бордо": "burgundy",
        "корич": "brown",
        "карам": "caramel",
        "золот": "gold",
        "сереб": "silver",
    }
    translated: list[str] = []
    for token in re.split(r"[,;/•]+", value.lower()):
        clean_token = token.strip()
        for key, color in color_map.items():
            if key in clean_token and color not in translated:
                translated.append(color)
    return translated


def build_mandatory_color_requirement(profile: dict[str, str]) -> str:
    colors = translate_color_preferences(profile.get("preferred_colors", ""))
    if not colors:
        return (
            f"Mandatory clothing palette: use the user's preferred colors exactly as written: "
            f"{profile.get('preferred_colors', '')}."
        )

    dominant = ", ".join(colors[:3])
    has_dark_neutral = any(color in {"black", "grey", "brown"} for color in colors)
    avoid_dark = (
        ""
        if has_dark_neutral
        else "Avoid black, charcoal, dark grey, navy, and brown as dominant garment colors. "
    )
    return (
        f"MANDATORY CLOTHING COLORS: the outfit garments must be visibly dominated by {dominant}. "
        "At least the main top or outer layer must clearly show one of these requested colors. "
        f"{avoid_dark}"
        "Do not replace the requested palette with generic grey or black sportswear."
    )


def build_garment_color_instruction(profile: dict[str, str]) -> str:
    colors = translate_color_preferences(profile.get("preferred_colors", ""))
    if not colors:
        return ""

    primary = colors[0]
    secondary = colors[1] if len(colors) > 1 else colors[0]
    category = safe_event_for_generation(profile, resolve_event_style(profile)).category

    if category == "sport":
        return (
            f"Exact color placement: make the hoodie, sport jacket, or technical top clearly {primary}; "
            f"make the secondary top, sneakers, stripe details, or bag clearly {secondary}. "
            "Do not make the main hoodie or jacket grey, charcoal, or black unless that exact color was requested."
        )
    if category in {"casual", "campus", "travel"}:
        return (
            f"Exact color placement: make the main top, knit, overshirt, or jacket clearly {primary}; "
            f"use {secondary} for trousers, shirt layer, shoes, or bag details."
        )
    if category in {"date", "party", "formal"}:
        return (
            f"Exact color placement: make the most visible garment clearly {primary}; "
            f"use {secondary} as the second visible garment or accessory color."
        )
    return (
        f"Exact color placement: main visible garment {primary}; "
        f"secondary visible garment or accessories {secondary}."
    )


def build_hair_requirement(profile: dict[str, str]) -> str:
    hair_color_map = {
        "Темные": "dark brown or black",
        "Русые": "dark blonde / light brown",
        "Светлые": "blonde",
        "Рыжие": "red / ginger",
    }
    texture_map = {
        "Прямые": "straight",
        "Волнистые": "wavy",
        "Кудрявые": "curly",
    }
    hair_color = hair_color_map.get(profile.get("hair", ""), profile.get("hair", ""))
    texture = texture_map.get(profile.get("hair_texture", ""), profile.get("hair_texture", ""))
    extra_texture_rule = "with defined curls, not straight or merely loose waves" if texture == "curly" else ""
    extra_color_rule = "not blonde, not light brown, not red hair" if "dark" in hair_color else ""
    return (
        f"MANDATORY HAIR: visible {hair_color} {texture} hair {extra_texture_rule} {extra_color_rule}. "
        "Do not change the hair color or hair texture from the questionnaire."
    )


def build_skin_requirement(profile: dict[str, str]) -> str:
    skin_map = {
        "Светлый": "light skin tone",
        "Средний": "medium skin tone",
        "Теплый": "warm skin undertone",
        "Оливковый": "olive skin tone",
        "Темный": "dark skin tone",
    }
    return f"MANDATORY SKIN TONE: {skin_map.get(profile.get('skin', ''), profile.get('skin', ''))}."


def collect_palette(profile: dict[str, str], analysis: dict[str, Any]) -> list[tuple[int, int, int]]:
    candidates = [
        profile.get("preferred_colors", ""),
        profile.get("eyes", ""),
        profile.get("hair", ""),
        profile.get("skin", ""),
        str(analysis.get("palette_strategy", "")),
        str(analysis.get("styling_notes", "")),
    ]
    colors: list[tuple[int, int, int]] = []
    for candidate in candidates:
        for token in re.split(r"[,;/•]+", candidate):
            rgb = parse_color_token(token)
            if rgb and rgb not in colors:
                colors.append(rgb)
    if not colors:
        colors = [(143, 93, 255), (255, 141, 216), (122, 230, 255)]
    return colors[:5]


def mix_color(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - ratio) + b[i] * ratio) for i in range(3))


def create_gradient_background(image: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = mix_color(top, bottom, ratio)
        draw.line((0, y, width, y), fill=color)


def draw_soft_glows(draw: ImageDraw.ImageDraw, width: int, height: int, palette: list[tuple[int, int, int]]) -> None:
    for idx, color in enumerate(palette[:3]):
        radius = 220 + idx * 70
        cx = int(width * (0.18 + idx * 0.28))
        cy = int(height * (0.14 + idx * 0.07))
        overlay = tuple(min(255, int(c * 1.1)) for c in color)
        box = (cx - radius, cy - radius, cx + radius, cy + radius)
        draw.ellipse(box, fill=overlay + (25,))


def draw_street_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    wall_top = (227, 224, 218)
    wall_bottom = (206, 201, 193)
    pavement_top = (84, 82, 80)
    pavement_bottom = (64, 62, 60)
    wall_h = int(height * 0.73)
    for y in range(wall_h):
        ratio = y / max(wall_h - 1, 1)
        draw.line((0, y, width, y), fill=mix_color(wall_top, wall_bottom, ratio))
    for y in range(wall_h, height):
        ratio = (y - wall_h) / max(height - wall_h - 1, 1)
        draw.line((0, y, width, y), fill=mix_color(pavement_top, pavement_bottom, ratio))
    draw.line((0, wall_h, width, wall_h), fill=(144, 140, 135), width=3)
    draw.rectangle((0, 0, width, 18), fill=(210, 207, 201))
    draw.line((width * 0.1, wall_h - 8, width * 0.9, wall_h - 8), fill=(170, 166, 160), width=2)


def draw_fashion_model(
    image: Image.Image,
    profile: dict[str, str],
    direction: LookDirection,
    analysis: dict[str, Any],
    variation_index: int,
    total_variations: int,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    palette = collect_palette(profile, analysis)
    primary = palette[0]
    accent = palette[1] if len(palette) > 1 else (255, 141, 216)
    secondary = palette[2] if len(palette) > 2 else (122, 230, 255)
    dark = (22, 16, 34)
    skin_tones = {
        "свет": (240, 211, 184),
        "смуг": (191, 140, 108),
        "олив": (183, 150, 114),
        "тем": (128, 85, 63),
        "тёп": (224, 182, 144),
    }
    skin = (218, 173, 138)
    skin_text = profile["skin"].lower()
    for key, value in skin_tones.items():
        if key in skin_text:
            skin = value
            break

    center_x = width // 2
    head_y = int(height * 0.20)
    shoulder_y = int(height * 0.29)
    chest_y = int(height * 0.39)
    waist_y = int(height * 0.57)
    hip_y = int(height * 0.71)
    feet_y = int(height * 0.92)

    # realistic head and neck
    head_w = 92
    head_h = 106
    draw.ellipse((center_x - head_w // 2, head_y - head_h // 2, center_x + head_w // 2, head_y + head_h // 2), fill=skin)
    draw.rounded_rectangle((center_x - 16, head_y + 40, center_x + 16, shoulder_y), radius=8, fill=skin)

    title = direction.title.lower()
    if variation_index == 1:
        tee = (61, 43, 36)
        pants = (238, 233, 221)
        bag = (87, 55, 33)
        shoe = (28, 24, 27)
        skin_shadow = mix_color(skin, (104, 78, 66), 0.2)
        # shoulders and torso
        draw.rounded_rectangle((center_x - 168, shoulder_y + 8, center_x + 168, waist_y - 12), radius=34, fill=tee)
        draw.rectangle((center_x - 152, shoulder_y + 30, center_x + 152, shoulder_y + 58), fill=mix_color(tee, (92, 65, 56), 0.25))
        draw.line((center_x - 128, shoulder_y + 18, center_x - 128, waist_y - 12), fill=(84, 64, 57), width=3)
        draw.line((center_x + 128, shoulder_y + 18, center_x + 128, waist_y - 12), fill=(84, 64, 57), width=3)
        # sleeves
        draw.rounded_rectangle((center_x - 208, shoulder_y + 30, center_x - 160, waist_y - 2), radius=18, fill=tee)
        draw.rounded_rectangle((center_x + 160, shoulder_y + 30, center_x + 208, waist_y - 2), radius=18, fill=tee)
        draw.line((center_x - 176, shoulder_y + 54, center_x - 160, shoulder_y + 54), fill=(100, 73, 63), width=3)
        draw.line((center_x + 160, shoulder_y + 54, center_x + 176, shoulder_y + 54), fill=(100, 73, 63), width=3)
        # trousers with folds
        left_leg = [(center_x - 146, waist_y - 2), (center_x - 70, waist_y - 2), (center_x - 86, feet_y - 20), (center_x - 150, feet_y - 22)]
        right_leg = [(center_x + 70, waist_y - 2), (center_x + 146, waist_y - 2), (center_x + 150, feet_y - 22), (center_x + 86, feet_y - 20)]
        draw.polygon(left_leg, fill=pants)
        draw.polygon(right_leg, fill=pants)
        draw.line((center_x - 110, waist_y + 2, center_x - 122, feet_y - 26), fill=(214, 206, 191), width=3)
        draw.line((center_x - 92, waist_y + 2, center_x - 98, feet_y - 24), fill=(214, 206, 191), width=2)
        draw.line((center_x + 110, waist_y + 2, center_x + 122, feet_y - 26), fill=(214, 206, 191), width=3)
        draw.line((center_x + 92, waist_y + 2, center_x + 98, feet_y - 24), fill=(214, 206, 191), width=2)
        draw.ellipse((center_x - 92, waist_y - 6, center_x + 92, waist_y + 18), fill=mix_color(pants, (210, 202, 190), 0.2))
        # bag and strap
        draw.line((center_x - 38, shoulder_y + 2, center_x + 82, waist_y + 8), fill=(97, 64, 38), width=16)
        draw.line((center_x - 38, shoulder_y + 2, center_x + 82, waist_y + 8), fill=(54, 40, 31), width=4)
        draw.rounded_rectangle((center_x - 200, waist_y + 4, center_x - 154, feet_y - 54), radius=14, fill=bag)
        draw.rounded_rectangle((center_x - 188, waist_y + 14, center_x - 166, feet_y - 42), radius=7, fill=mix_color(bag, accent, 0.18))
        # arms and hand details
        arm = mix_color(skin, skin_shadow, 0.3)
        draw.rounded_rectangle((center_x - 206, shoulder_y + 34, center_x - 166, waist_y - 6), radius=18, fill=arm)
        draw.rounded_rectangle((center_x + 158, shoulder_y + 34, center_x + 198, waist_y - 6), radius=18, fill=arm)
        draw.ellipse((center_x - 204, waist_y - 4, center_x - 172, waist_y + 28), fill=arm)
        # shoes with toe detail
        draw.rounded_rectangle((center_x - 154, feet_y - 42, center_x - 60, feet_y - 14), radius=14, fill=shoe)
        draw.rounded_rectangle((center_x + 60, feet_y - 42, center_x + 154, feet_y - 14), radius=14, fill=shoe)
        draw.ellipse((center_x - 148, feet_y - 38, center_x - 108, feet_y - 18), fill=(236, 232, 223))
        draw.ellipse((center_x + 108, feet_y - 38, center_x + 148, feet_y - 18), fill=(236, 232, 223))
    elif "smart" in title or "weekend" in title:
        tee = mix_color(primary, dark, 0.2)
        pants = mix_color(accent, (245, 237, 226), 0.55)
        draw.rounded_rectangle((center_x - 152, shoulder_y + 18, center_x + 152, waist_y - 10), radius=30, fill=tee)
        draw.polygon([(center_x - 146, waist_y), (center_x + 146, waist_y), (center_x + 104, feet_y - 24), (center_x - 104, feet_y - 24)], fill=pants)
        draw.rounded_rectangle((center_x - 196, shoulder_y + 30, center_x - 158, waist_y - 8), radius=16, fill=mix_color(skin, dark, 0.1))
        draw.rounded_rectangle((center_x + 158, shoulder_y + 30, center_x + 196, waist_y - 8), radius=16, fill=mix_color(skin, dark, 0.1))
        draw.rounded_rectangle((center_x - 120, feet_y - 44, center_x - 36, feet_y - 16), radius=12, fill=mix_color(dark, primary, 0.2))
        draw.rounded_rectangle((center_x + 36, feet_y - 44, center_x + 120, feet_y - 16), radius=12, fill=mix_color(dark, primary, 0.2))
    elif "power" in title or "executive" in title or "avant" in title:
        jacket = mix_color(primary, dark, 0.25)
        pants = mix_color(dark, secondary, 0.3)
        draw.rounded_rectangle((center_x - 156, shoulder_y + 10, center_x + 156, hip_y), radius=42, fill=jacket)
        draw.polygon(
            [(center_x - 156, shoulder_y + 34), (center_x, chest_y + 28), (center_x + 156, shoulder_y + 34), (center_x + 120, hip_y), (center_x - 120, hip_y)],
            fill=mix_color(jacket, primary, 0.18),
        )
        draw.polygon([(center_x - 120, hip_y), (center_x - 18, hip_y), (center_x - 52, feet_y), (center_x - 156, feet_y)], fill=pants)
        draw.polygon([(center_x + 18, hip_y), (center_x + 120, hip_y), (center_x + 156, feet_y), (center_x + 52, feet_y)], fill=pants)
        arm = mix_color(skin, dark, 0.08)
        draw.rounded_rectangle((center_x - 204, shoulder_y + 30, center_x - 160, hip_y - 16), radius=18, fill=arm)
        draw.rounded_rectangle((center_x + 160, shoulder_y + 30, center_x + 204, hip_y - 16), radius=18, fill=arm)
        shoe = mix_color(dark, primary, 0.18)
        draw.rounded_rectangle((center_x - 156, feet_y - 50, center_x - 54, feet_y - 22), radius=14, fill=shoe)
        draw.rounded_rectangle((center_x + 54, feet_y - 50, center_x + 156, feet_y - 22), radius=14, fill=shoe)
    elif "evening" in title or "signature" in title or "date" in title:
        gown = mix_color(primary, accent, 0.28)
        draw.polygon(
            [(center_x - 98, shoulder_y + 6), (center_x + 98, shoulder_y + 6), (center_x + 144, hip_y), (center_x + 96, feet_y), (center_x - 96, feet_y), (center_x - 144, hip_y)],
            fill=gown,
        )
        draw.rounded_rectangle((center_x - 190, shoulder_y + 36, center_x - 150, waist_y - 10), radius=16, fill=mix_color(skin, dark, 0.08))
        draw.rounded_rectangle((center_x + 150, shoulder_y + 36, center_x + 190, waist_y - 10), radius=16, fill=mix_color(skin, dark, 0.08))
        draw.rounded_rectangle((center_x - 110, feet_y - 48, center_x - 30, feet_y - 18), radius=14, fill=mix_color(dark, primary, 0.18))
        draw.rounded_rectangle((center_x + 30, feet_y - 48, center_x + 110, feet_y - 18), radius=14, fill=mix_color(dark, primary, 0.18))
    else:
        top = mix_color(primary, secondary, 0.4)
        bottom = mix_color(accent, dark, 0.15)
        draw.rounded_rectangle((center_x - 150, shoulder_y + 14, center_x + 150, waist_y - 4), radius=30, fill=top)
        draw.polygon(
            [(center_x - 140, waist_y), (center_x + 140, waist_y), (center_x + 108, feet_y - 22), (center_x - 108, feet_y - 22)],
            fill=bottom,
        )
        draw.rounded_rectangle((center_x - 190, shoulder_y + 34, center_x - 148, waist_y - 8), radius=16, fill=mix_color(skin, dark, 0.08))
        draw.rounded_rectangle((center_x + 148, shoulder_y + 34, center_x + 190, waist_y - 8), radius=16, fill=mix_color(skin, dark, 0.08))
        draw.rounded_rectangle((center_x - 116, feet_y - 48, center_x - 32, feet_y - 18), radius=14, fill=mix_color(dark, primary, 0.16))
        draw.rounded_rectangle((center_x + 32, feet_y - 48, center_x + 116, feet_y - 18), radius=14, fill=mix_color(dark, primary, 0.16))

    # gentle pose shadow and hand-in-pocket feel
    draw.ellipse((center_x - 220, feet_y - 8, center_x + 220, feet_y + 28), fill=(0, 0, 0, 28))
    draw.line((center_x + 34, shoulder_y + 8, center_x + 42, waist_y - 4), fill=(255, 255, 255, 50), width=4)
    draw.line((center_x - 12, shoulder_y + 28, center_x - 42, waist_y - 8), fill=(255, 255, 255, 24), width=3)
    draw.line((center_x + 54, shoulder_y + 6, center_x + 160, shoulder_y + 48), fill=accent + (150,), width=6)

    # Caption
    draw.rounded_rectangle((68, 70, width - 68, 182), radius=30, fill=(9, 7, 18, 150))
    draw.text((108, 94), f"Look {variation_index:02d} of {total_variations}", fill=(245, 240, 255), font=resolve_font(28, True))
    draw.text((108, 132), direction.title, fill=(255, 255, 255), font=resolve_font(42, True))
    draw.text((width - 108, 94), profile["event"], fill=(205, 187, 234), font=resolve_font(24), anchor="ra")

    # Bottom style strip
    strip_y = int(height * 0.95)
    strip_colors = palette[:4]
    strip_x = 96
    for color in strip_colors:
        draw.rounded_rectangle((strip_x, strip_y, strip_x + 138, strip_y + 26), radius=12, fill=color + (255,))
        strip_x += 152


def render_free_fashion_mockup(
    profile: dict[str, str],
    direction: LookDirection,
    analysis: dict[str, Any],
    variation_index: int,
    total_variations: int,
) -> bytes:
    image = Image.new("RGB", (1024, 1536), (12, 8, 22))
    palette = collect_palette(profile, analysis)
    draw_street_background(ImageDraw.Draw(image), image.size[0], image.size[1])

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw_soft_glows(draw, image.size[0], image.size[1], palette)
    draw.rounded_rectangle((52, 50, image.size[0] - 52, image.size[1] - 52), radius=44, outline=(255, 255, 255, 32), width=3)
    draw.rounded_rectangle((82, 224, image.size[0] - 82, 1310), radius=58, fill=(10, 7, 18, 42))
    draw_fashion_model(overlay, profile, direction, analysis, variation_index, total_variations)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_body_guidance(profile: dict[str, str]) -> str:
    kibbe = determine_kibbe_archetype(profile)
    kibbe_clothing = kibbe_clothing_for_profile(profile, kibbe)
    return (
        f"{build_body_shape_lock(profile)} "
        f"{build_body_visual_description(profile)} "
        "Use the body measurements to adapt the silhouette, garment fit, waist emphasis, "
        "hemlines, layering volume, and proportions of the outfit. "
        f"Height: {profile['height']}. Weight: {profile['weight']}. Age: {profile['age']}. "
        f"Upper circumference: {profile['bust']}. Waist: {profile['waist']}. Lower circumference: {profile['hips']}. "
        f"Kibbe archetype: {kibbe.name}. Kibbe line: {kibbe.line}. "
        f"Recommended Kibbe clothing: {kibbe_clothing}. Avoid: {kibbe.avoid}. "
        "The outfit should look intentionally chosen for this body, not generic."
    )


def build_occasion_guidance(profile: dict[str, str]) -> str:
    original_event_style = resolve_event_style(profile)
    event_label = profile["event"]
    if is_minor_profile(profile) and original_event_style.category == "date":
        event_label = "дружеская встреча или дневная прогулка"
    elif is_minor_profile(profile) and original_event_style.category == "party":
        event_label = "молодёжное вечернее мероприятие, концерт или танцевальная студия"
    return (
        f"Occasion or meeting type: {event_label}. "
        f"{build_event_outfit_rules(profile)} "
        "Choose garments, shoes, accessories, and styling formality that fit this exact context."
    )


def is_minor_profile(profile: dict[str, str]) -> bool:
    return profile_number(profile, "age") < 18


def safe_event_for_generation(profile: dict[str, str], event_style: EventStyleBrief) -> EventStyleBrief:
    if is_minor_profile(profile) and event_style.category == "date":
        return EventStyleBrief(
            category="casual",
            outfit="age-appropriate casual outfit for a friendly daytime meeting or walk, modest and non-romantic",
            footwear="comfortable casual shoes",
            accessories="simple age-appropriate accessories",
            avoid="keep the styling modest, fully clothed, friendly, and appropriate for a safe daytime social setting",
            scene="age-appropriate casual daytime street-style photo, friendly meeting context, non-romantic",
        )
    if is_minor_profile(profile) and event_style.category == "party":
        return EventStyleBrief(
            category="youth_social",
            outfit="age-appropriate evening casual outfit for a concert, creative school event, or dance studio social; modest, stylish, fully clothed",
            footwear="comfortable stylish sneakers, loafers, or flat boots",
            accessories="simple practical accessories, small bag, safe social styling",
            avoid="keep the styling modest, fully clothed, non-romantic, and appropriate for a safe creative social setting",
            scene="safe creative evening social setting, concert-inspired or dance-studio-inspired fashion photo, non-adult context",
        )
    return event_style


def build_color_guidance(profile: dict[str, str]) -> str:
    return (
        f"Preferred colors: {profile['preferred_colors']}. "
        f"Appearance cues: {profile['eyes']} eyes, {profile['hair']} hair color, "
        f"{profile.get('hair_texture', '')} hair texture, {profile['skin']} skin tone. "
        "Build a palette that harmonizes with both the requested colors and the person's appearance."
    )


def user_requested_nonstandard_garment(profile: dict[str, str], *needles: str) -> bool:
    text = profile.get("extra_preferences", "").lower()
    return any(needle in text for needle in needles)


def build_user_preference_instruction(profile: dict[str, str]) -> str:
    extra_preferences = profile.get("extra_preferences", "").strip()
    if not extra_preferences:
        return "User extra preferences: none."

    instruction = (
        f"MANDATORY USER EXTRA PREFERENCES: {extra_preferences}. "
        "Treat these preferences as higher priority than generic style templates, as long as they do not change the selected person identity. "
        "If the user asks for a specific garment, it must be visible in the outfit."
    )
    if profile.get("gender") == "Мужской" and user_requested_nonstandard_garment(
        profile,
        "юбк",
        "юпк",
        "skirt",
        "килт",
        "kilt",
        "плать",
        "dress",
    ):
        instruction += (
            " This is an intentionally nonstandard male styling request: keep ONE male model with masculine body and face, "
            "but include the requested skirt/dress-like garment as fashion styling, for example a kilt-inspired skirt, long skirt, or layered skirt silhouette. "
            "Do not replace the male model with a woman."
        )
    return instruction


def build_gender_identity_lock(profile: dict[str, str]) -> str:
    is_male = profile["gender"] == "Мужской"
    if not is_male and is_minor_profile(profile):
        return (
            "STRICT IDENTITY: ONE FEMALE MODEL ONLY, youthful age-neutral presentation, "
            "safe modest womenswear styling, face cropped or de-emphasized. "
        )
    if is_male and user_requested_nonstandard_garment(
        profile,
        "юбк",
        "юпк",
        "skirt",
        "килт",
        "kilt",
        "плать",
        "dress",
    ):
        if is_minor_profile(profile):
            return (
                "STRICT IDENTITY: ONE MALE MODEL ONLY, youthful clean-shaven appearance, no beard, "
                "no mature adult facial hair. Gender stays male, but user explicitly allows a "
                "nonstandard skirt/dress-like garment in the outfit. "
            )
        return (
            "STRICT IDENTITY: ONE MALE MAN ONLY, masculine body and face. "
            "Gender stays male, but user explicitly allows a nonstandard skirt/dress-like garment in the outfit. "
        )
    if is_male:
        if is_minor_profile(profile):
            return (
                "STRICT IDENTITY: ONE MALE MODEL ONLY, youthful clean-shaven appearance, no beard, "
                "no mature adult facial hair, masculine outfit styling. "
            )
        return "STRICT IDENTITY: ONE MALE MAN ONLY, masculine body, masculine menswear, no feminine styling. "
    return "STRICT IDENTITY: ONE FEMALE WOMAN ONLY, feminine fashion silhouette, womenswear styling. "


def build_image_prompt(
    profile: dict[str, str],
    direction: LookDirection,
    analysis: dict[str, Any],
    variation_index: int,
    total_variations: int,
) -> str:
    is_male = profile["gender"] == "Мужской"
    age_line = build_image_age_line(profile)
    gender_prompt = (
        f"single {age_line}, male model wearing masculine menswear"
        if is_male and is_minor_profile(profile)
        else f"single {age_line}, male man wearing masculine menswear"
        if is_male
        else f"single {age_line}, female woman wearing womenswear"
    )
    allows_male_skirt = is_male and user_requested_nonstandard_garment(
        profile,
        "юбк",
        "юпк",
        "skirt",
        "килт",
        "kilt",
        "плать",
        "dress",
    )
    gender_rule = (
        "Generate ONLY a male model with masculine fashion silhouette. The user explicitly requested a nonstandard skirt/dress-like garment, so include that garment while keeping the model male. Do not generate women or female bodies."
        if allows_male_skirt
        else "Generate ONLY a male model with masculine fashion silhouette and masculine clothing. Do not generate women, female bodies, dresses, skirts, blouses, high heels, or feminine womenswear."
        if is_male
        else "Generate ONLY a female model with feminine fashion silhouette and womenswear. Do not generate men or masculine menswear unless explicitly requested."
    )
    return (
        f"Vertical portrait photorealistic full-body fashion photo of exactly ONE {gender_prompt}. "
        "Create ONE realistic outfit recommendation photo, like a premium clothing brand editorial, not a collage or wardrobe overview. "
        f"{gender_rule} "
        "Hard composition rule: one real fashion model, one body, one pose, one outfit, one background, one camera frame. "
        "The frame must not be divided into panels. Do not show a lineup, collection, catalog grid, contact sheet, collage, side-by-side comparison, multiple models, repeated bodies, duplicated same person, or multiple outfits in the same image. "
        "Center the single model in the frame with clear space around the body; show the outfit from shoulders or neck down to shoes. "
        "Frame the model from neck or shoulders to shoes if needed; the face may be cropped out, turned away, or visually de-emphasized. "
        "The focus must be real clothes, fit, fabric, silhouette, footwear, and accessories on one body. "
        "Create only this single look for one person. "
        f"Selected gender: {gender_prompt} ({profile['gender']}). Match this gender exactly; do not generate another gender. "
        f"{build_body_shape_lock(profile)} {build_safe_image_body_description(profile)} "
        f"{build_occasion_guidance(profile)} "
        f"{build_color_guidance(profile)} "
        f"Desired overall impression: {profile['style_goals']}. "
        f"{build_user_preference_instruction(profile)} "
        f"Stylist analysis silhouette strategy: {analysis.get('silhouette_strategy', '')}. "
        f"Stylist analysis palette strategy: {analysis.get('palette_strategy', '')}. "
        f"Stylist analysis outfit focus: {analysis.get('outfit_focus', '')}. "
        f"Kibbe archetype to follow: {analysis.get('kibbe_archetype', '')}. "
        f"Kibbe clothing line: {analysis.get('kibbe_clothing', '')}. "
        f"Recommended footwear: {analysis.get('footwear', '')}. "
        f"Recommended accessories: {analysis.get('accessories', '')}. "
        f"Detailed styling notes: {analysis.get('styling_notes', '')}. "
        f"Avoid these decisions: {analysis.get('avoid', '')}. "
        f"Styling direction for this variation: {direction.styling_note}. "
        f"Variation label: {direction.title}. "
        f"Scene and camera treatment: {direction.scene_note}. "
        "Generate one outfit that clearly reflects the questionnaire data and Kibbe archetype in silhouette, color palette, fabric choice, layering, footwear, and accessories. "
        "Make this look distinct by changing the garment focus, styling angle, or mood while keeping the same overall brief. "
        "The result must look like a believable stylist recommendation specifically made for this person and this occasion, not a generic fashion photo. "
        "Keep the clothes elegant, wearable, premium, and realistic. "
        "Use real-life wearable garments, natural fabric folds, realistic seams, believable shoes, real-world lighting, and authentic proportions. "
        "No illustration, no drawing, no cartoon, no anime, no 3D render, no mannequin, no paper-doll look, no collage, no text, no extra people, no lineup, no clothing collection, no split image, no duplicated limbs, no cropped feet."
    )


def build_cloudflare_image_prompt(
    profile: dict[str, str],
    direction: LookDirection,
    analysis: dict[str, Any],
    variation_index: int,
) -> str:
    is_male = profile["gender"] == "Мужской"
    original_event_style = resolve_event_style(profile)
    event_style = safe_event_for_generation(profile, original_event_style)
    event_label = profile["event"]
    if is_minor_profile(profile) and original_event_style.category == "date":
        event_label = "дружеская встреча или дневная прогулка"
    elif is_minor_profile(profile) and original_event_style.category == "party":
        event_label = "молодёжное вечернее мероприятие, концерт или танцевальная студия"
    variation_style = build_event_variation_style(profile, variation_index)
    identity_lock = build_gender_identity_lock(profile)
    allows_male_skirt = is_male and user_requested_nonstandard_garment(
        profile,
        "юбк",
        "юпк",
        "skirt",
        "килт",
        "kilt",
        "плать",
        "dress",
    )
    age_line = build_image_age_line(profile)
    gender_line = (
        f"one {age_line}, male model, masculine fashion silhouette, user-requested nonstandard skirt/dress-like garment is allowed"
        if allows_male_skirt
        else f"one {age_line}, male model, masculine fashion silhouette, masculine menswear only"
        if is_male
        else f"one {age_line}, female model, feminine fashion silhouette, modest womenswear only"
    )
    minor_male_face_rule = ", no beard, no mature adult facial hair" if is_male and is_minor_profile(profile) else ""
    forbidden_gender = (
        f"no women, no female body, no high heels, no feminine blouse{minor_male_face_rule}; skirt/kilt is allowed only because user requested it"
        if allows_male_skirt
        else f"no women, no dresses, no skirts, no heels, no feminine blouse{minor_male_face_rule}"
        if is_male
        else "no men, no beard, no masculine suit unless requested"
    )
    formal_block = ""
    if event_style.category not in {"business", "formal"}:
        formal_block = (
            "This is NOT a business, office, corporate, or formal suit outfit. "
            "Do not use a blazer suit, tie, corporate dress shirt, formal office trousers, or boardroom styling. "
        )
    prompt = (
        f"{identity_lock}"
        f"{build_body_shape_lock(profile)} "
        f"{build_user_preference_instruction(profile)} "
        f"CRITICAL EVENT: {event_label}. Event category: {event_style.category}. "
        f"MANDATORY outfit for this image: {variation_style}. "
        f"{build_mandatory_color_requirement(profile)} "
        f"{build_garment_color_instruction(profile)} "
        f"{build_hair_requirement(profile)} "
        f"{build_skin_requirement(profile)} "
        f"{formal_block}"
        f"Photorealistic vertical full-body lifestyle fashion photo, exactly {gender_line}. "
        f"Scene must match event: {event_style.scene}. "
        "Single person only, one outfit only, one pose, one clean realistic background. "
        "No lineup, no collage, no catalog grid, no panels, no repeated person, no multiple outfits, no text. "
        f"{forbidden_gender}. "
        f"{build_safe_image_body_description(profile)} "
        f"Kibbe archetype: {analysis.get('kibbe_archetype', '')}; line: {analysis.get('kibbe_line', '')}. "
        f"Kibbe clothing adaptation: {analysis.get('kibbe_clothing', '')}. "
        f"{build_event_outfit_rules(profile)} "
        f"Preferred colors in Russian: {profile['preferred_colors']}. "
        f"Eye color: {profile['eyes']}; hair: {profile['hair']}, {profile.get('hair_texture', '')}; skin tone: {profile['skin']}. "
        f"Subtle variation mood: {direction.vibe}; use it only if it does not conflict with the event. "
        f"Footwear: {analysis.get('footwear', '')}. Accessories: {analysis.get('accessories', '')}. "
        "Real clothes, realistic fabric folds, believable fit, natural proportions, modern wearable styling."
    )
    return prompt[:2000]


def get_image_provider_config() -> tuple[str | None, str]:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        return "openrouter", openrouter_key

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        return "openai", openai_key

    return None, ""


def get_cloudflare_image_config() -> tuple[str, str, str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    model = os.environ.get(
        "CLOUDFLARE_IMAGE_MODEL",
        DEFAULT_CLOUDFLARE_IMAGE_MODEL,
    ).strip()
    if not token:
        raise RuntimeError("Не задан CLOUDFLARE_API_TOKEN для Cloudflare Workers AI.")
    if not account_id:
        raise RuntimeError(
            "Не задан CLOUDFLARE_ACCOUNT_ID. Откройте Cloudflare Dashboard → Workers & Pages → AI "
            "или правую панель аккаунта и добавьте Account ID в .env."
        )
    if not model:
        raise RuntimeError("Не задана модель CLOUDFLARE_IMAGE_MODEL.")
    return token, account_id, model


def extract_cloudflare_image_bytes(response_data: dict[str, Any]) -> bytes:
    result = response_data.get("result")
    if isinstance(result, str):
        encoded = result
    elif isinstance(result, dict):
        encoded = (
            result.get("image")
            or result.get("b64_json")
            or result.get("base64")
            or ""
        )
        images = result.get("images")
        if not encoded and isinstance(images, list) and images:
            first_image = images[0]
            if isinstance(first_image, str):
                encoded = first_image
            elif isinstance(first_image, dict):
                encoded = (
                    first_image.get("image")
                    or first_image.get("b64_json")
                    or first_image.get("base64")
                    or ""
                )
    else:
        encoded = ""

    if not encoded:
        errors = response_data.get("errors") or []
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else ""
        raise RuntimeError(message or "Cloudflare Workers AI не вернул изображение.")

    if encoded.startswith("data:image"):
        _, _, encoded = encoded.partition(",")
    return base64.b64decode(encoded)


def generate_image_with_cloudflare(prompt: str) -> bytes:
    token, account_id, model = get_cloudflare_image_config()
    model_path = url_quote(model, safe="@/")
    endpoint = CLOUDFLARE_API_ENDPOINT.format(
        account_id=account_id,
        model=model_path,
    )
    payload = {
        "prompt": prompt,
    }

    body = json.dumps(payload).encode("utf-8")
    request_obj = urllib_request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib_request.urlopen(request_obj, timeout=240) as response:
            content_type = response.headers.get("Content-Type", "")
            body_bytes = response.read()
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(details)
            errors = parsed.get("errors") or []
            api_message = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        except json.JSONDecodeError:
            api_message = None
        raise RuntimeError(
            api_message or "Cloudflare Workers AI вернул ошибку при генерации изображений."
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            "Не удалось подключиться к Cloudflare Workers AI для генерации изображений."
        ) from exc

    if content_type.startswith("image/"):
        return body_bytes

    try:
        response_data = json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Cloudflare Workers AI вернул неожиданный формат ответа.") from exc

    if response_data.get("success") is False:
        errors = response_data.get("errors") or []
        api_message = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        raise RuntimeError(api_message or "Cloudflare Workers AI не смог сгенерировать изображение.")

    return extract_cloudflare_image_bytes(response_data)


def extract_image_bytes_from_response(response_data: dict[str, Any]) -> bytes:
    choices = response_data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter не вернул результат генерации.")

    message = choices[0].get("message") or {}
    images = message.get("images") or []
    if not images:
        raise RuntimeError("OpenRouter не вернул изображение в ответе.")

    image_url = (
        images[0].get("image_url", {}).get("url")
        or images[0].get("imageUrl", {}).get("url")
        or ""
    )
    if not image_url.startswith("data:image"):
        raise RuntimeError("Получен неожиданный формат изображения от OpenRouter.")

    _, _, encoded = image_url.partition(",")
    return base64.b64decode(encoded)


def generate_image_with_openai(prompt: str, api_key: str) -> bytes:
    payload = {
        "model": os.environ.get("OPENAI_IMAGE_MODEL", DEFAULT_OPENAI_IMAGE_MODEL),
        "prompt": prompt,
        "size": "1024x1536",
        "quality": "medium",
        "output_format": "png",
        "n": 1,
    }
    body = json.dumps(payload).encode("utf-8")
    request_obj = urllib_request.Request(
        OPENAI_IMAGE_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib_request.urlopen(request_obj, timeout=240) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(details)
            api_message = parsed.get("error", {}).get("message")
        except json.JSONDecodeError:
            api_message = None
        raise RuntimeError(
            api_message or "OpenAI вернул ошибку при генерации изображений."
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            "Не удалось подключиться к OpenAI для генерации изображений."
        ) from exc

    images = response_data.get("data", [])
    if not images or not images[0].get("b64_json"):
        raise RuntimeError("OpenAI не вернул изображение в ответе.")

    return base64.b64decode(images[0]["b64_json"])


def generate_image_with_openrouter(prompt: str, api_key: str) -> bytes:

    payload = {
        "model": os.environ.get("OPENROUTER_IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "16:10"},
    }
    body = json.dumps(payload).encode("utf-8")
    request_obj = urllib_request.Request(
        OPENROUTER_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("STYLE_SENSE_APP_URL", "http://127.0.0.1:5000"),
            "X-Title": "Style Sense AI",
        },
    )

    try:
        with urllib_request.urlopen(request_obj, timeout=240) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(details)
            api_message = parsed.get("error", {}).get("message")
        except json.JSONDecodeError:
            api_message = None
        raise RuntimeError(
            api_message or "OpenRouter вернул ошибку при генерации изображений."
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            "Не удалось подключиться к OpenRouter для генерации изображений."
        ) from exc

    return extract_image_bytes_from_response(response_data)


def build_negative_prompt(profile: dict[str, str] | None = None) -> str:
    negative = (
        "illustration, drawing, cartoon, anime, sketch, painting, vector art, "
        "3d render, cgi, mannequin, doll, paper doll, plastic skin, fake texture, "
        "low detail, blurry, low quality, bad anatomy, extra fingers, duplicated limbs, "
        "cropped feet, out of frame, text, watermark, logo, collage, split image, "
        "multiple people, many people, two people, group photo, lineup, model lineup, "
        "fashion collection, catalog grid, contact sheet, triptych, diptych, panels, divided frame, "
        "side by side outfits, multiple outfit options, wardrobe overview, repeated person, duplicate model, "
        "same person repeated three times, cloned model, "
        "wrong gender, unrelated body type, generic outfit unrelated to the questionnaire"
    )
    if profile and profile.get("gender") == "Мужской":
        if user_requested_nonstandard_garment(
            profile,
            "юбк",
            "юпк",
            "skirt",
            "килт",
            "kilt",
            "плать",
            "dress",
        ):
            negative += ", woman, women, female, feminine model, blouse, high heels, makeup editorial beauty lineup"
        else:
            negative += ", woman, women, female, feminine model, dress, skirt, blouse, high heels, makeup editorial beauty lineup"
    elif profile and profile.get("gender") == "Женский":
        negative += ", man, men, male, masculine model, beard, male suit if not requested"
    return negative


def get_hf_image_model() -> str:
    return os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell").strip()


def get_hf_image_provider() -> str:
    return os.environ.get("HF_IMAGE_PROVIDER", "hf-inference").strip() or "hf-inference"


def get_local_image_model() -> str:
    return os.environ.get("LOCAL_IMAGE_MODEL", DEFAULT_LOCAL_IMAGE_MODEL).strip()


def get_local_image_int_setting(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def get_local_image_float_setting(name: str, default: float) -> float:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def load_local_image_pipeline():
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
    except Exception as exc:  # pragma: no cover - depends on local package stack
        raise RuntimeError(
            "Не удалось подключить локальный генератор изображений. Проверьте, что установлены torch и diffusers."
        ) from exc

    model_id = get_local_image_model()
    device = "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    dtype = torch.float16 if device in {"mps", "cuda"} else torch.float32

    load_kwargs: dict[str, Any] = {
        "torch_dtype": dtype,
        "use_safetensors": True,
    }
    variant = os.environ.get("LOCAL_IMAGE_VARIANT", "").strip()
    if variant:
        load_kwargs["variant"] = variant

    try:
        pipeline = AutoPipelineForText2Image.from_pretrained(model_id, **load_kwargs)
    except Exception:
        load_kwargs.pop("variant", None)
        pipeline = AutoPipelineForText2Image.from_pretrained(model_id, **load_kwargs)
    if not any(marker in model_id.lower() for marker in ("turbo", "schnell")):
        try:
            from diffusers import DPMSolverMultistepScheduler

            pipeline.scheduler = DPMSolverMultistepScheduler.from_config(
                pipeline.scheduler.config,
                use_karras_sigmas=True,
            )
        except Exception:
            pass
    pipeline = pipeline.to(device)
    try:
        pipeline.set_progress_bar_config(disable=True)
    except Exception:
        pass
    if device == "cpu":
        try:
            pipeline.enable_attention_slicing()
        except Exception:
            pass
    return pipeline, device


def generate_image_with_huggingface(prompt: str, profile: dict[str, str]) -> bytes:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - depends on local package stack
        raise RuntimeError("Не удалось загрузить torch для локальной генерации изображений.") from exc

    try:
        pipeline, device = load_local_image_pipeline()
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": build_negative_prompt(profile),
            "width": get_local_image_int_setting("LOCAL_IMAGE_WIDTH", 832),
            "height": get_local_image_int_setting("LOCAL_IMAGE_HEIGHT", 1216),
            "generator": torch.Generator().manual_seed(secrets.randbelow(2**32)),
        }
        model_name = get_local_image_model().lower()
        if "turbo" in model_name or "schnell" in model_name:
            kwargs["num_inference_steps"] = get_local_image_int_setting("LOCAL_IMAGE_STEPS", 6)
            kwargs["guidance_scale"] = get_local_image_float_setting("LOCAL_IMAGE_GUIDANCE", 1.6)
        else:
            kwargs["num_inference_steps"] = get_local_image_int_setting("LOCAL_IMAGE_STEPS", 30)
            kwargs["guidance_scale"] = get_local_image_float_setting("LOCAL_IMAGE_GUIDANCE", 7.0)

        result = pipeline(**kwargs)
        image = result.images[0]
    except Exception as exc:
        raise RuntimeError(
            f"Не удалось сгенерировать фотореалистичный образ локально: {exc}"
        ) from exc

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_and_store_looks(user_id: int, profile: dict[str, str]) -> list[dict[str, Any]]:
    clear_generated_looks(user_id)
    analysis = analyze_profile_free(profile)
    kibbe_name = str(analysis.get("kibbe_archetype", "Кибби"))
    meta = f"{kibbe_name} • {profile['preferred_colors']} • {profile['event']}"
    profile_note = (
        f"{profile['gender']} • {profile['age']} лет • {profile['height']} / {profile['weight']} • "
        f"ОГ {profile['bust']} / ОТ {profile['waist']} / ОБ {profile['hips']} • "
        f"{profile.get('body_shape', '')} • {profile.get('limb_length', '')} конечности • "
        f"{profile['hair']} волосы • {profile.get('hair_texture', '')} • {profile['skin']} кожа"
    )

    look_directions = look_directions_for_profile(profile)
    total_variations = len(look_directions)
    for index, direction in enumerate(look_directions, start=1):
        event_style = safe_event_for_generation(profile, resolve_event_style(profile))
        card_title = build_event_look_title(profile, index)
        card_vibe = f"{event_category_label_ru(event_style.category)} • {direction.vibe}"
        prompt = build_cloudflare_image_prompt(profile, direction, analysis, index)
        image_bytes = generate_image_with_cloudflare(prompt)
        reason = build_display_reason_ru(profile, index, kibbe_name, analysis)
        note = build_display_note_ru(profile, index, direction, analysis)
        save_generated_look(
            user_id=user_id,
            title=card_title,
            vibe=card_vibe,
            meta=meta,
            note=note,
            profile_note=profile_note,
            reason=reason,
            prompt=prompt,
            image_bytes=image_bytes,
            source=f"cloudflare:{os.environ.get('CLOUDFLARE_IMAGE_MODEL', DEFAULT_CLOUDFLARE_IMAGE_MODEL).strip()}",
        )

    return fetch_generated_looks(user_id, set())


@app.get("/")
def landing():
    return render_template("index.html")


@app.get("/auth")
def auth_page():
    user_id = current_user_id()
    if user_id is not None and fetch_user(user_id) is not None:
        return redirect(url_for("cabinet"))
    return render_template("auth.html")


@app.get("/forgot-password")
def forgot_password_page():
    return render_template("forgot_password.html")


@app.get("/reset-password")
def reset_password_code_page():
    return render_template("reset_password_code.html")


@app.get("/privacy-policy")
def privacy_policy_page():
    return render_template(
        "privacy_policy.html",
        policy_version=POLICY_VERSION,
        operator_name=os.environ.get(
            "STYLE_SENSE_OPERATOR_NAME",
            "ElanTech",
        ),
        operator_email=os.environ.get(
            "STYLE_SENSE_OPERATOR_EMAIL",
            "elizaku@sfedu.ru",
        ),
        operator_address=os.environ.get(
            "STYLE_SENSE_OPERATOR_ADDRESS",
            "Некрасовский пер., 42, Таганрог, Ростовская обл., 347922",
        ),
        operator_phone=os.environ.get(
            "STYLE_SENSE_OPERATOR_PHONE",
            "Уточните контактный телефон оператора",
        ),
    )


@app.get("/reset-password/<token>")
def reset_password_page(token: str):
    reset_row = find_valid_password_reset(token)
    if reset_row is None:
        return render_template("reset_password.html", token=token, token_valid=False)
    return render_template("reset_password.html", token=token, token_valid=True)


@app.get("/cabinet")
def cabinet():
    user_id = current_user_id()
    if user_id is None or fetch_user(user_id) is None:
        return redirect(url_for("auth_page"))
    return render_template("cabinet.html")


@app.get("/questionnaire")
def questionnaire_page():
    user_id = current_user_id()
    if user_id is None or fetch_user(user_id) is None:
        return redirect(url_for("auth_page"))
    return render_template("questionnaire.html")


@app.get("/favorites")
def favorites_page():
    user_id = current_user_id()
    if user_id is None or fetch_user(user_id) is None:
        return redirect(url_for("auth_page"))
    return render_template("favorites.html")


@app.get("/looks/<look_id>")
def look_detail_page(look_id: str):
    user_id = current_user_id()
    if user_id is None or fetch_user(user_id) is None:
        return redirect(url_for("auth_page"))

    look = fetch_generated_look(user_id, look_id)
    if look is None:
        return redirect(url_for("questionnaire_page"))
    return render_template("look_detail.html", look=look)


@app.get("/api/session")
def api_session() -> Any:
    user_id = current_user_id()
    if user_id is None:
        return jsonify({"authenticated": False})
    return jsonify(profile_payload(user_id))


@app.post("/api/register")
def api_register() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", "")).strip()
    privacy_consent = bool(payload.get("privacy_consent"))

    if not EMAIL_RE.match(email):
        return json_error("Введите корректный email.")
    if len(password) < 6:
        return json_error("Пароль должен содержать минимум 6 символов.")
    if not privacy_consent:
        return json_error("Нужно согласиться с политикой конфиденциальности и обработкой персональных данных.")

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        return json_error("Пользователь с таким email уже зарегистрирован.", 409)

    cursor = db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (email, generate_password_hash(password)),
    )
    db.commit()

    session["user_id"] = cursor.lastrowid
    log_consent_event(
        "personal_data_consent",
        user_id=cursor.lastrowid,
        email=email,
        source_page="/auth",
    )
    return jsonify(
        {
            "message": "Аккаунт создан. Теперь можно заполнить анкету и получить 10 персональных образов.",
            **profile_payload(cursor.lastrowid),
        }
    )




@app.post("/api/login")
def api_login() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", "")).strip()

    row = get_db().execute(
        "SELECT id, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return json_error("Неверный email или пароль.", 401)

    session["user_id"] = row["id"]
    return jsonify(
        {
            "message": "Вход выполнен. Личный кабинет снова доступен.",
            **profile_payload(row["id"]),
        }
    )


@app.post("/api/logout")
def api_logout() -> Any:
    session.clear()
    return jsonify({"message": "Сессия завершена."})


@app.post("/api/password/forgot")
def api_password_forgot() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    if not EMAIL_RE.match(email):
        return json_error("Введите корректный email.")

    row = get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        return jsonify(
            {
                "message": "Если такой email зарегистрирован, код для восстановления уже отправлен.",
            }
        )

    code = create_password_reset_code(int(row["id"]))
    sent, error_message = send_password_reset_email(email, code)
    response = {
        "message": "Код для восстановления отправлен на почту." if sent else "SMTP не настроен или не удалось отправить письмо.",
        "redirectUrl": url_for("reset_password_code_page"),
        "email": email,
        "nextUrl": f"{url_for('reset_password_code_page')}?email={url_quote(email)}",
    }
    if not sent:
        response["recoveryCode"] = code
        if error_message:
            response["debug"] = error_message
            response["message"] = error_message
    return jsonify(response)


@app.post("/api/password/reset")
def api_password_reset() -> Any:
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token", "")).strip()
    password = str(payload.get("password", "")).strip()

    if len(password) < 6:
        return json_error("Пароль должен содержать минимум 6 символов.")

    reset_row = find_valid_password_reset(token)
    if reset_row is None:
        return json_error("Ссылка для восстановления недействительна или устарела.", 400)

    db = get_db()
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), int(reset_row["user_id"])),
    )
    db.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
        (utc_now().isoformat(), int(reset_row["id"])),
    )
    db.commit()

    return jsonify({"message": "Пароль обновлён. Теперь можно войти с новым паролем."})


@app.post("/api/password/reset-by-code")
def api_password_reset_by_code() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    code = str(payload.get("code", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not EMAIL_RE.match(email):
        return json_error("Введите корректный email.")
    if not re.fullmatch(r"\d{6}", code):
        return json_error("Введите 6-значный код.")
    if len(password) < 6:
        return json_error("Пароль должен содержать минимум 6 символов.")

    reset_row = find_valid_password_reset_code(email, code)
    if reset_row is None:
        return json_error("Код недействителен или срок его действия истёк.", 400)

    db = get_db()
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), int(reset_row["user_id"])),
    )
    db.execute(
        "UPDATE password_reset_codes SET used_at = ? WHERE id = ?",
        (utc_now().isoformat(), int(reset_row["id"])),
    )
    db.commit()

    return jsonify({"message": "Пароль обновлён. Теперь можно войти с новым паролем."})


@app.post("/api/questionnaire")
def api_questionnaire() -> Any:
    user_id = current_user_id()
    if user_id is None:
        return json_error("Сначала войдите в аккаунт.", 401)

    payload = request.get_json(silent=True) or {}
    required_fields = {
        "gender": "Выберите пол или стилистическое направление.",
        "limb_length": "Выберите длину конечностей относительно тела.",
        "cheekbones": "Выберите описание скул.",
        "height": "Укажите рост.",
        "weight": "Укажите вес.",
        "age": "Укажите возраст.",
        "bust": "Укажите обхват груди.",
        "waist": "Укажите обхват талии.",
        "hips": "Укажите обхват бёдер.",
        "body_shape": "Выберите форму тела.",
        "lip_size": "Выберите размер губ.",
        "hair_texture": "Выберите структуру волос.",
        "eyes": "Выберите цвет глаз.",
        "hair": "Выберите цвет волос.",
        "skin": "Выберите оттенок кожи.",
        "event": "Опишите тип мероприятия.",
        "preferred_colors": "Выберите предпочтительные цвета.",
    }

    for field, error_message in required_fields.items():
        if not str(payload.get(field, "")).strip():
            return json_error(error_message)

    normalized_payload, validation_error = validate_questionnaire_payload(payload)
    if validation_error is not None or normalized_payload is None:
        return json_error(validation_error or "Проверьте данные анкеты.")

    profile = {
        "gender": normalized_payload["gender"],
        "limb_length": normalized_payload["limb_length"],
        "cheekbones": normalized_payload["cheekbones"],
        "height": normalized_payload["height"],
        "weight": normalized_payload["weight"],
        "age": normalized_payload["age"],
        "proportions": "",
        "bust": normalized_payload["bust"],
        "waist": normalized_payload["waist"],
        "hips": normalized_payload["hips"],
        "body_shape": normalized_payload["body_shape"],
        "lip_size": normalized_payload["lip_size"],
        "hair_texture": normalized_payload["hair_texture"],
        "eyes": normalized_payload["eyes"],
        "hair": normalized_payload["hair"],
        "skin": normalized_payload["skin"],
        "event": normalized_payload["event"],
        "preferred_colors": normalized_payload["preferred_colors"],
        "style_goals": str(payload.get("style_goals", "сбалансированный и уместный образ")).strip()
        or "сбалансированный и уместный образ",
        "extra_preferences": normalized_payload["extra_preferences"],
    }

    db = get_db()
    available_columns = table_columns(db, "questionnaires")
    record = {
        "user_id": user_id,
        "gender": profile["gender"],
        "limb_length": profile["limb_length"],
        "cheekbones": profile["cheekbones"],
        "height": profile["height"],
        "weight": profile["weight"],
        "age": profile["age"],
        "proportions": profile["proportions"],
        "bust": profile["bust"],
        "waist": profile["waist"],
        "hips": profile["hips"],
        "body_shape": profile["body_shape"],
        "lip_size": profile["lip_size"],
        "hair_texture": profile["hair_texture"],
        "eyes": profile["eyes"],
        "hair": profile["hair"],
        "skin": profile["skin"],
        "event_type": profile["event"],
        "preferred_colors": profile["preferred_colors"],
        "style_goals": profile["style_goals"],
        "extra_preferences": profile["extra_preferences"],
    }

    if "mood" in available_columns:
        record["mood"] = profile["style_goals"]
    if "palette" in available_columns:
        record["palette"] = profile["preferred_colors"]
    if "extra_wishes" in available_columns:
        record["extra_wishes"] = profile["extra_preferences"]

    columns = [name for name in record if name in available_columns]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(
        f"{column} = excluded.{column}" for column in columns if column != "user_id"
    )
    sql = f"""
        INSERT INTO questionnaires ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(user_id) DO UPDATE SET
            {updates},
            updated_at = CURRENT_TIMESTAMP
    """
    db.execute(sql, tuple(record[column] for column in columns))
    db.commit()

    try:
        looks = generate_and_store_looks(user_id, profile)
    except RuntimeError as exc:
        return json_error(humanize_generation_error(str(exc)), 503)

    message = "AI сгенерировал 10 образов по вашей анкете. Можно выбрать лучшие и сохранить их в избранное."

    return jsonify(
        {
            "message": message,
            "questionnaire": profile,
            "looks": looks,
            "favoritesCount": 0,
            "favorites": [],
        }
    )


@app.post("/api/favorites")
def api_favorites() -> Any:
    user_id = current_user_id()
    if user_id is None:
        return json_error("Сначала войдите в аккаунт.", 401)

    payload = request.get_json(silent=True) or {}
    look_id = str(payload.get("look_id", "")).strip()
    favorite = bool(payload.get("favorite", False))

    existing = get_db().execute(
        "SELECT id FROM generated_looks WHERE id = ? AND user_id = ?",
        (look_id, user_id),
    ).fetchone()
    if existing is None:
        return json_error("Не удалось сохранить образ.", 404)

    db = get_db()
    if favorite:
        db.execute(
            "INSERT OR IGNORE INTO favorites (user_id, look_id) VALUES (?, ?)",
            (user_id, look_id),
        )
    else:
        db.execute(
            "DELETE FROM favorites WHERE user_id = ? AND look_id = ?",
            (user_id, look_id),
        )
    db.commit()

    state = profile_payload(user_id)
    return jsonify(
        {
            "message": "Избранное обновлено.",
            "favoritesCount": state["favoritesCount"],
            "favorites": state["favorites"],
        }
    )


@app.get("/api/favorites")
def api_favorites_list() -> Any:
    user_id = current_user_id()
    if user_id is None:
        return json_error("Сначала войдите в аккаунт.", 401)

    state = profile_payload(user_id)
    favorite_ids = set(state["favorites"])
    favorite_looks = [look for look in state["looks"] if look["id"] in favorite_ids]
    return jsonify(
        {
            "favoritesCount": state["favoritesCount"],
            "looks": favorite_looks,
        }
    )


init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
        use_reloader=False,
    )
