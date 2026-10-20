r"""Migratsiya runner'i — `docs/11` MVP sxemasini bosqichma-bosqich qo'llash.

Bu modul **yangi kutubxona talab qilmaydi** (faqat `aiosqlite`, loyihada bor).

Nega kerak
----------
`database/db.py` ilgari butun sxemani `executescript(SCHEMA_SQL)` bilan bir marta
yaratardi. Endi `docs/11-FINAL-MVP-DATABASE-MODEL.md` bo'yicha MVP jadvallari
(qariyb 15 ta) **bosqichma-bosqich** qo'shiladi; bu ishni boshqarish uchun
`schema_migrations` jadvali va tartiblangan migratsiya fayllari kerak.

Fayl nomlash qoidasi
--------------------
    <version>_<name>.sql          — "up" (migratsiyani qo'llash)
    <version>_<name>.down.sql     — "down" (orqaga qaytarish)

Masalan: `001_item_bank.sql` / `001_item_bank.down.sql`.
`version` — raqamli prefiks (`001`), tartiblash shu bo'yicha boradi.

Idempotentlik
-------------
1. Har bir DDL buyrug'i `IF NOT EXISTS` bilan yozilgan — qayta ishga tushirish
   xavfsiz;
2. `schema_migrations` jadvalidagi yozuv allaqachon qo'llangan versiyalarni
   o'tkazib yuboradi;
3. Fayl kontenti o'zgarganini `checksum` (SHA-256) orqali aniqlaydi
   (o'zgargan bo'lsa — ogohlantiradi, `--strict` bilan xato beradi).

Cheklov (muhim)
---------------
SQLite'da `executescript` tranzaksiyani oldin commit qiladi, shuning uchun
migratsiya **yarim qo'llanib qolishi** mumkin. Bunga qarshi: (a) hamma DDL
`IF NOT EXISTS`, (b) `schema_migrations` yozuvi faqat skript muvaffaqiyatli
bajarilgandan keyin qo'shiladi — ya'ni qayta ishga tushirish muammoni
tuzatadi (yangi jadvallar mavjud bo'lganlari bilan qayta yaratilmaydi).

Rollback strategiyasi
---------------------
* **Asosiy usul** — `.down.sql` fayllari (`--rollback <version>`):
  faqat shu migratsiya yaratgan jadvallarni o'chiradi (bola -> ota tartibida).
* Rollback **teskari tartibda** bajariladi: 005 -> 004 -> 003 -> 002 -> 001
  (chunki `items` ni `responses` ishlatadi va h.k.).
* **Zaxira (birinchi chora)** — migratsiyadan oldin baza faylini nusxalash:
      copy data\math_bot.db data\backup\math_bot_before_migrations.db
  Bu — eng ishonchli yo'l (docs/05 rollback qoidasi).
* Legacy jadvallar (`users`, `questions`, `test_results`, `exams`,
  `user_answers`, `solutions`) migratsiyalar bilan **tegilmaydi** — ular
  backward compatibility uchun joyida qoladi.

Ishlatish
---------
    # nima qo'llanishini ko'rish (yozmaydi)
    python -m database.migrate --db data/math_bot.db --dry-run

    # qo'llash
    python -m database.migrate --db data/math_bot.db

    # ma'lum versiyagacha
    python -m database.migrate --db data/math_bot.db --to 003

    # orqaga qaytarish (bitta versiya)
    python -m database.migrate --db data/math_bot.db --rollback 005

Bundan tashqari `Database.connect()` ishga tushganda migratsiyalar avtomatik
qo'llanadi (`database/db.py` ga qo'shilgan bitta chaqiruv).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# Migratsiya fayllari joylashgan papka (bu fayl bilan bir qatorda).
MIGRATIONS_DIR: Path = Path(__file__).resolve().parent / "migrations"

# Fayl nomi: 001_item_bank.sql  ->  version="001", name="item_bank"
MIGRATION_RE = re.compile(r"^(?P<version>\d+)_(?P<name>[A-Za-z0-9_]+)\.sql$")

# Rollback faylining qo'shimchasi: 001_item_bank.down.sql
DOWN_SUFFIX = ".down.sql"

# Migratsiyalar jadvali (docs/11 §5.5: version, name, checksum, applied_at, duration_ms)
SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    checksum    TEXT,
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    duration_ms INTEGER
);
"""


@dataclass(frozen=True, slots=True)
class Migration:
    """Bitta migratsiya fayli (up + ixtiyoriy down)."""

    version: str          # "001"
    name: str             # "item_bank"
    path: Path            # up fayl yo'li
    down_path: Path | None  # down fayl yo'li (bo'lmasa None)
    checksum: str         # up fayl SHA-256 (o'zgarganini aniqlash uchun)

    @property
    def label(self) -> str:
        """Log/xabarlarda ko'rsatiladigan nom: `001_item_bank`."""
        return f"{self.version}_{self.name}"


def _checksum(path: Path) -> str:
    """Fayl kontentining SHA-256 hashi (checksum)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_migrations(migrations_dir: Path | None = None) -> list[Migration]:
    """Papkadagi barcha migratsiyalarni topadi va **versiya bo'yicha** tartiblaydi.

    `.down.sql` fayllari alohida migratsiya sifatida olinmaydi — ular up faylga
    juftlanadi. Nom qoidasiga mos kelmagan fayllar e'tiborga olinmaydi.

    Raises:
        FileNotFoundError: migratsiyalar papkasi topilmasa.
    """
    directory = Path(migrations_dir or MIGRATIONS_DIR)
    if not directory.exists():
        raise FileNotFoundError(f"Migratsiyalar papkasi topilmadi: {directory}")

    found: dict[str, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        if path.name.endswith(DOWN_SUFFIX):
            continue  # down fayllar alohida ko'riladi
        match = MIGRATION_RE.match(path.name)
        if match is None:
            logger.warning("Migratsiya nomi qoidaga mos emas, o'tkazib yuborildi: %s", path.name)
            continue

        version = match.group("version")
        name = match.group("name")
        down_path = directory / f"{version}_{name}{DOWN_SUFFIX}"
        found[version] = Migration(
            version=version,
            name=name,
            path=path,
            down_path=down_path if down_path.exists() else None,
            checksum=_checksum(path),
        )

    return [found[version] for version in sorted(found)]


# ---------------------------------------------------------------------------
# Qo'llash (apply)
# ---------------------------------------------------------------------------
async def ensure_migrations_table(conn: aiosqlite.Connection) -> None:
    """`schema_migrations` jadvalini (bo'lmasa) yaratadi."""
    await conn.executescript(SCHEMA_MIGRATIONS_SQL)
    await conn.commit()


async def applied_versions(conn: aiosqlite.Connection) -> dict[str, str | None]:
    """Qo'llangan migratsiyalar: {version: checksum} ko'rinishida."""
    cursor = await conn.execute("SELECT version, checksum FROM schema_migrations")
    rows = await cursor.fetchall()
    await cursor.close()
    return {str(row[0]): (str(row[1]) if row[1] is not None else None) for row in rows}


def _split_statements(sql: str) -> str:
    """Skriptni o'zgartirmasdan qaytaradi (izohlar va `;` ichida saqlanadi).

    Bu yordamchi ataylab "no-op": `executescript` ko'p buyruqli skriptni
    o'zi bajaradi. Funksiya kelajakda qator-darajali nazorat kerak bo'lsa
    (masalan, buyruqlarni loglash) ishlatiladi va hozir o'qish uchun qulaylik
    yaratadi.
    """
    return sql


async def apply_migrations(
    conn: aiosqlite.Connection,
    *,
    migrations_dir: Path | None = None,
    to_version: str | None = None,
    dry_run: bool = False,
    strict: bool = False,
) -> list[str]:
    """Migratsiyalarni tartib bilan qo'llaydi (idempotent).

    Args:
        conn: ochiq `aiosqlite` ulanishi (foreign_keys allaqachon yoqilgan).
        migrations_dir: migratsiyalar papkasi (default — `database/migrations`).
        to_version: shu versiyagacha qo'llash (masalan `"003"`).
        dry_run: `True` bo'lsa hech narsa yozilmaydi — faqat ro'yxat qaytadi.
        strict: `True` bo'lsa, fayli o'zgargan (checksum mos kelmagan)
            migratsiya xato beradi; `False` bo'lsa — ogohlantirish bilan o'tadi.

    Returns:
        Qo'llangan (yoki `dry_run` da — qo'llanishi kerak bo'lgan) versiyalar
        ro'yxati.
    """
    migrations = discover_migrations(migrations_dir)
    await ensure_migrations_table(conn)
    already = await applied_versions(conn)

    applied: list[str] = []
    for migration in migrations:
        if to_version and migration.version > to_version:
            logger.debug("To'xtatildi (`--to %s`): %s o'tkazib yuborildi",
                         to_version, migration.label)
            break

        recorded_checksum = already.get(migration.version)
        if recorded_checksum is not None:
            # Allaqachon qo'llangan — idempotentlik shu yerda ta'minlanadi.
            if recorded_checksum != migration.checksum:
                message = (
                    f"Migratsiya fayli o'zgargan: {migration.label} "
                    f"(yozilgan={recorded_checksum[:12]}, hozir={migration.checksum[:12]})"
                )
                if strict:
                    raise RuntimeError(message)
                logger.warning("%s — e'tibor bering (strict=False)", message)
            continue

        if dry_run:
            applied.append(migration.version)
            logger.info("[DRY-RUN] Qo'llanadi: %s", migration.label)
            continue

        started = time.monotonic()
        sql = _split_statements(migration.path.read_text(encoding="utf-8"))
        await conn.executescript(sql)
        duration_ms = int((time.monotonic() - started) * 1000)
        await conn.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, duration_ms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (version) DO UPDATE SET
                name        = excluded.name,
                checksum    = excluded.checksum,
                applied_at  = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
                duration_ms = excluded.duration_ms
            """,
            (migration.version, migration.name, migration.checksum, duration_ms),
        )
        await conn.commit()
        applied.append(migration.version)
        logger.info("Migratsiya qo'llandi: %s (%d ms)", migration.label, duration_ms)

    if not applied:
        logger.info("Migratsiyalar dolzarb — yangi o'zgarish yo'q")
    return applied


# ---------------------------------------------------------------------------
# Orqaga qaytarish (rollback)
# ---------------------------------------------------------------------------
async def rollback_migration(
    conn: aiosqlite.Connection,
    version: str,
    *,
    migrations_dir: Path | None = None,
) -> bool:
    """Bitta migratsiyani `.down.sql` fayli bo'yicha orqaga qaytaradi.

    Returns:
        `True` — rollback bajarildi; `False` — migratsiya qo'llanmagan yoki
        down fayli yo'q.

    Raises:
        ValueError: bunday versiyali migratsiya topilmasa.

    Diqqat:
        Rollback **teskari tartibda** bajarilishi kerak (005 -> 004 -> ... -> 001),
        chunki `items`/`form_versions` kabi ota jadvallarni bola jadvallar
        (`responses`, `attempts`) ishlatadi.
    """
    migrations = {item.version: item for item in discover_migrations(migrations_dir)}
    migration = migrations.get(version)
    if migration is None:
        raise ValueError(f"Bunday versiyali migratsiya topilmadi: {version!r}")

    await ensure_migrations_table(conn)
    already = await applied_versions(conn)
    if version not in already:
        logger.warning("Migratsiya qo'llanmagan: %s — rollback shart emas", migration.label)
        return False

    higher = sorted(item for item in already if item > version)
    if higher:
        logger.warning(
            "Rollback tartibi buzilgan: %s hali ham qo'llangan. Avval ularni "
            "qaytaring: %s",
            ", ".join(higher),
            " ".join(f"--rollback {item}" for item in reversed(higher)),
        )

    if migration.down_path is None:
        logger.error(
            "Rollback fayli topilmadi: %s (kutilgan fayl: %s%s)",
            migration.label,
            migration.label,
            DOWN_SUFFIX,
        )
        return False

    sql = migration.down_path.read_text(encoding="utf-8")
    await conn.executescript(sql)
    await conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
    await conn.commit()
    logger.info("Rollback bajarildi: %s", migration.label)
    return True


# ---------------------------------------------------------------------------
# CLI uchun qulay o'ramlar (o'z ulanishini ochadi)
# ---------------------------------------------------------------------------
async def run_migrations(
    db_path: str | Path,
    *,
    to_version: str | None = None,
    dry_run: bool = False,
    strict: bool = False,
) -> list[str]:
    """Bazaga ulanib migratsiyalarni qo'llaydi (CLI uchun)."""
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        result = await apply_migrations(
            conn, to_version=to_version, dry_run=dry_run, strict=strict
        )
        await conn.commit()
        return result


async def run_rollback(db_path: str | Path, version: str) -> bool:
    """Bazaga ulanib bitta migratsiyani orqaga qaytaradi (CLI uchun)."""
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        return await rollback_migration(conn, version)


def build_parser() -> argparse.ArgumentParser:
    """CLI argumentlarini tayyorlaydi."""
    parser = argparse.ArgumentParser(
        prog="python -m database.migrate",
        description="MVP sxema migratsiyalarini qo'llash (docs/11).",
    )
    parser.add_argument(
        "--db",
        default="data/math_bot.db",
        help="Baza fayli yo'li (default: data/math_bot.db)",
    )
    parser.add_argument(
        "--to",
        dest="to_version",
        default=None,
        help="Shu versiyagacha qo'llash (masalan 003)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Hech narsa yozmasdan, qo'llanishi kerak bo'lganlarni ko'rsatish",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fayli o'zgargan migratsiya uchun xato berish (checksum mos kelmasa)",
    )
    parser.add_argument(
        "--rollback",
        default=None,
        help="Shu versiyani orqaga qaytarish (masalan 005). Teskari tartibda qiling!",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Mavjud migratsiyalar ro'yxatini ko'rsatish",
    )
    return parser


async def _main(argv: list[str] | None = None) -> int:
    """CLI kirish nuqtasi (`python -m database.migrate ...`)."""
    args = build_parser().parse_args(argv)

    if args.list:
        for migration in discover_migrations():
            down = "bor" if migration.down_path else "yo'q"
            print(f"{migration.label}  (rollback: {down})")
        return 0

    if args.rollback:
        done = await run_rollback(args.db, args.rollback)
        print("Rollback bajarildi." if done else "Rollback bajarilmadi (sabab logda).")
        return 0 if done else 1

    applied = await run_migrations(
        args.db,
        to_version=args.to_version,
        dry_run=args.dry_run,
        strict=args.strict,
    )
    if args.dry_run:
        print(f"[DRY-RUN] Qo'llanadi: {', '.join(applied) if applied else '—'}")
    else:
        print(f"Qo'llandi: {', '.join(applied) if applied else '—'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    import sys

    if hasattr(sys.stdout, "reconfigure"):  # Windows konsoli uchun (UTF-8)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(asyncio.run(_main()))


