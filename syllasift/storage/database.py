import sqlite3
import uuid


DATABASE_NAME = "SyllaSift.db"
SCHEMA_VERSION = 2


def get_connection():
    connection = sqlite3.connect(DATABASE_NAME)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_exists(connection, table_name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _column_names(connection, table_name):
    return {
        row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _create_schema(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            auth_subject TEXT NOT NULL UNIQUE,
            email TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            course_name TEXT NOT NULL,
            course_code TEXT,
            semester TEXT NOT NULL,
            year INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE (course_id, user_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS deadlines (
            deadline_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            course_id INTEGER NOT NULL,
            item TEXT NOT NULL,
            raw_date TEXT,
            due_date TEXT NOT NULL,
            is_completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (course_id, user_id)
                REFERENCES courses(course_id, user_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_courses_user_id ON courses(user_id)"
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_deadlines_user_course
        ON deadlines(user_id, course_id)
        """
    )


def _create_uniqueness_indexes(connection):
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_courses_owned_identity
        ON courses(
            user_id,
            CASE
                WHEN trim(coalesce(course_code, '')) <> '' THEN
                    'code:' || lower(replace(replace(trim(course_code), '-', ''), ' ', ''))
                ELSE 'name:' || lower(trim(course_name))
            END,
            lower(trim(semester)), year
        )
        WHERE user_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_deadlines_owned_identity
        ON deadlines(user_id, course_id, lower(trim(item)), due_date)
        WHERE user_id IS NOT NULL
        """
    )


def _course_identity(course_name, course_code, semester, year):
    code = "".join(
        character for character in str(course_code or "").casefold()
        if character not in {" ", "-"}
    )
    label = (
        f"code:{code}" if code
        else f"name:{str(course_name).strip().casefold()}"
    )
    return label, str(semester).strip().casefold(), int(year)


def _deduplicate_owned_data(connection):
    courses = connection.execute(
        """
        SELECT course_id, user_id, course_name, course_code, semester, year
        FROM courses WHERE user_id IS NOT NULL ORDER BY course_id
        """
    ).fetchall()
    survivors = {}
    for course_id, user_id, name, code, semester, year in courses:
        key = (user_id, *_course_identity(name, code, semester, year))
        survivor = survivors.setdefault(key, course_id)
        if survivor != course_id:
            connection.execute(
                """
                UPDATE deadlines SET course_id = ?
                WHERE course_id = ? AND user_id = ?
                """,
                (survivor, course_id, user_id),
            )
            connection.execute(
                "DELETE FROM courses WHERE course_id = ? AND user_id = ?",
                (course_id, user_id),
            )

    groups = connection.execute(
        """
        SELECT user_id, course_id, lower(trim(item)), due_date,
               min(deadline_id), max(is_completed), min(completed_at)
        FROM deadlines WHERE user_id IS NOT NULL
        GROUP BY user_id, course_id, lower(trim(item)), due_date
        HAVING count(*) > 1
        """
    ).fetchall()
    for (
        user_id, course_id, item_key, due_date,
        survivor, completed, completed_at,
    ) in groups:
        connection.execute(
            """
            UPDATE deadlines SET is_completed = ?, completed_at = ?
            WHERE deadline_id = ?
            """,
            (completed, completed_at if completed else None, survivor),
        )
        connection.execute(
            """
            DELETE FROM deadlines
            WHERE user_id = ? AND course_id = ? AND lower(trim(item)) = ?
              AND due_date = ? AND deadline_id <> ?
            """,
            (user_id, course_id, item_key, due_date, survivor),
        )


def _create_ownership_triggers(connection):
    # Ownership columns stay nullable only so preserved legacy rows can exist.
    statements = (
        """
        CREATE TRIGGER IF NOT EXISTS courses_require_owner
        BEFORE INSERT ON courses
        WHEN NEW.user_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'courses require an owner');
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS courses_owner_is_immutable
        BEFORE UPDATE OF user_id ON courses
        WHEN NEW.user_id IS NOT OLD.user_id
        BEGIN
            SELECT RAISE(ABORT, 'course ownership is immutable');
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS deadlines_require_owner
        BEFORE INSERT ON deadlines
        WHEN NEW.user_id IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'deadlines require an owner');
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS deadlines_owner_is_immutable
        BEFORE UPDATE OF user_id ON deadlines
        WHEN NEW.user_id IS NOT OLD.user_id
        BEGIN
            SELECT RAISE(ABORT, 'deadline ownership is immutable');
        END
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _migrate_legacy_schema(connection):
    has_courses = _table_exists(connection, "courses")
    has_deadlines = _table_exists(connection, "deadlines")
    courses_are_legacy = has_courses and "user_id" not in _column_names(
        connection, "courses"
    )
    deadlines_are_legacy = has_deadlines and "user_id" not in _column_names(
        connection, "deadlines"
    )

    if not courses_are_legacy and not deadlines_are_legacy:
        _create_schema(connection)
        return

    if deadlines_are_legacy:
        connection.execute("ALTER TABLE deadlines RENAME TO deadlines_legacy")
    if courses_are_legacy:
        connection.execute("ALTER TABLE courses RENAME TO courses_legacy")

    _create_schema(connection)
    if courses_are_legacy:
        connection.execute(
            """
            INSERT INTO courses (
                course_id, user_id, course_name, course_code, semester, year
            )
            SELECT course_id, NULL, course_name, course_code, semester, year
            FROM courses_legacy
            """
        )
    if deadlines_are_legacy:
        connection.execute(
            """
            INSERT INTO deadlines (
                deadline_id, user_id, course_id, item, raw_date, due_date,
                is_completed, created_at, completed_at
            )
            SELECT deadline_id, NULL, course_id, item, raw_date, due_date,
                   is_completed, created_at, completed_at
            FROM deadlines_legacy
            """
        )
        connection.execute("DROP TABLE deadlines_legacy")
    if courses_are_legacy:
        connection.execute("DROP TABLE courses_legacy")


def initialize_database():
    connection = get_connection()
    try:
        # Serialize first-run schema migrations across Streamlit sessions.
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than this app supports."
            )
        if version < SCHEMA_VERSION:
            _migrate_legacy_schema(connection)
            _deduplicate_owned_data(connection)
            _create_uniqueness_indexes(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        else:
            _create_schema(connection)
            _create_uniqueness_indexes(connection)
        _create_ownership_triggers(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.close()


def _require_user_id(user_id):
    if not str(user_id or "").strip():
        raise ValueError("An authenticated user ID is required.")


def get_or_create_user(auth_subject, email=None):
    subject = str(auth_subject or "").strip()
    if not subject:
        raise ValueError("An authenticated subject is required.")

    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT user_id FROM users WHERE auth_subject = ?", (subject,)
        ).fetchone()
        if row:
            if email:
                connection.execute(
                    "UPDATE users SET email = ? WHERE user_id = ?",
                    (str(email), row[0]),
                )
                connection.commit()
            return row[0]

        user_id = str(uuid.uuid4())
        try:
            connection.execute(
                """
                INSERT INTO users (user_id, auth_subject, email)
                VALUES (?, ?, ?)
                """,
                (user_id, subject, str(email) if email else None),
            )
            connection.commit()
            return user_id
        except sqlite3.IntegrityError:
            row = connection.execute(
                "SELECT user_id FROM users WHERE auth_subject = ?", (subject,)
            ).fetchone()
            if row:
                return row[0]
            raise
    finally:
        connection.close()


def save_course(user_id, course_name, course_code, semester, year):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO courses (
                user_id, course_name, course_code, semester, year
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, course_name, course_code, semester, year),
        )
        course_id = cursor.lastrowid
        connection.commit()
        return course_id
    finally:
        connection.close()


def save_deadlines(user_id, course_id, table_rows):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        owned_course = connection.execute(
            "SELECT 1 FROM courses WHERE course_id = ? AND user_id = ?",
            (course_id, user_id),
        ).fetchone()
        if not owned_course:
            raise ValueError("Course not found.")

        connection.executemany(
            """
            INSERT INTO deadlines (
                user_id, course_id, item, raw_date, due_date,
                is_completed, completed_at
            )
            VALUES (?, ?, ?, ?, ?, 0, NULL)
            """,
            [
                (
                    user_id,
                    course_id,
                    row["Item"],
                    row["Date"],
                    row["Normalized Date"],
                )
                for row in table_rows
            ],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def upsert_course_with_deadlines(
    user_id, course_name, course_code, semester, year, table_rows,
):
    """Atomically reuse/create a course and add only unseen deadlines."""
    _require_user_id(user_id)
    identity = _course_identity(course_name, course_code, semester, year)
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        courses = connection.execute(
            """
            SELECT course_id, course_name, course_code, semester, year
            FROM courses WHERE user_id = ? ORDER BY course_id
            """,
            (user_id,),
        ).fetchall()
        existing = next(
            (
                row for row in courses
                if _course_identity(row[1], row[2], row[3], row[4]) == identity
            ),
            None,
        )
        created = existing is None
        if created:
            cursor = connection.execute(
                """
                INSERT INTO courses (
                    user_id, course_name, course_code, semester, year
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, course_name, course_code, semester, year),
            )
            course_id = cursor.lastrowid
        else:
            course_id = existing[0]

        inserted = 0
        for row in table_rows:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO deadlines (
                    user_id, course_id, item, raw_date, due_date,
                    is_completed, completed_at
                ) VALUES (?, ?, ?, ?, ?, 0, NULL)
                """,
                (
                    user_id, course_id, row["Item"], row["Date"],
                    row["Normalized Date"],
                ),
            )
            inserted += cursor.rowcount
        connection.commit()
        return {
            "course_id": course_id,
            "course_created": created,
            "deadlines_inserted": inserted,
            "deadlines_skipped": len(table_rows) - inserted,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_course_options(user_id):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT course_id, course_name
            FROM courses
            WHERE user_id = ?
            ORDER BY course_name
            """,
            (user_id,),
        ).fetchall()
    finally:
        connection.close()


def get_courses_for_export(user_id):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT course_id, course_name, course_code, semester, year
            FROM courses
            WHERE user_id = ?
            ORDER BY year, semester, course_code, course_name
            """,
            (user_id,),
        ).fetchall()
        return [
            {
                "course_id": row[0],
                "course_name": row[1],
                "course_code": row[2],
                "semester": row[3],
                "year": row[4],
            }
            for row in rows
        ]
    finally:
        connection.close()


def get_deadlines_for_export(user_id, course_ids):
    _require_user_id(user_id)
    if not course_ids:
        return []

    normalized_ids = [int(course_id) for course_id in course_ids]
    placeholders = ", ".join("?" for _ in normalized_ids)
    connection = get_connection()
    try:
        rows = connection.execute(
            f"""
            SELECT
                d.deadline_id,
                c.course_id,
                c.course_name,
                c.course_code,
                c.semester,
                c.year,
                d.item,
                d.due_date,
                d.is_completed
            FROM deadlines AS d
            JOIN courses AS c
              ON c.course_id = d.course_id AND c.user_id = d.user_id
            WHERE c.user_id = ?
              AND d.user_id = ?
              AND c.course_id IN ({placeholders})
              AND d.is_completed = 0
            ORDER BY d.due_date, c.course_code, c.course_name, d.item
            """,
            [user_id, user_id, *normalized_ids],
        ).fetchall()
        return [
            {
                "deadline_id": row[0],
                "course_id": row[1],
                "course_name": row[2],
                "course_code": row[3],
                "semester": row[4],
                "year": row[5],
                "item": row[6],
                "due_date": row[7],
                "is_completed": bool(row[8]),
            }
            for row in rows
        ]
    finally:
        connection.close()


def get_deadlines(user_id, course_id):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT
                d.deadline_id,
                d.course_id,
                d.item,
                d.raw_date,
                d.due_date,
                d.is_completed,
                d.created_at,
                d.completed_at
            FROM deadlines AS d
            JOIN courses AS c
              ON c.course_id = d.course_id AND c.user_id = d.user_id
            WHERE d.course_id = ? AND d.user_id = ? AND c.user_id = ?
            ORDER BY d.due_date
            """,
            (course_id, user_id, user_id),
        ).fetchall()
    finally:
        connection.close()


def update_deadline_status(user_id, deadline_id, is_completed):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        if is_completed:
            cursor = connection.execute(
                """
                UPDATE deadlines
                SET is_completed = 1, completed_at = CURRENT_TIMESTAMP
                WHERE deadline_id = ? AND user_id = ?
                  AND EXISTS (
                      SELECT 1 FROM courses
                      WHERE courses.course_id = deadlines.course_id
                        AND courses.user_id = ?
                  )
                """,
                (deadline_id, user_id, user_id),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE deadlines
                SET is_completed = 0, completed_at = NULL
                WHERE deadline_id = ? AND user_id = ?
                  AND EXISTS (
                      SELECT 1 FROM courses
                      WHERE courses.course_id = deadlines.course_id
                        AND courses.user_id = ?
                  )
                """,
                (deadline_id, user_id, user_id),
            )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def get_dashboard_stats(user_id):
    _require_user_id(user_id)
    connection = get_connection()
    try:
        total_courses = connection.execute(
            "SELECT COUNT(*) FROM courses WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        total_deadlines, completed = connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(is_completed), 0)
            FROM deadlines
            WHERE user_id = ?
              AND EXISTS (
                  SELECT 1 FROM courses
                  WHERE courses.course_id = deadlines.course_id
                    AND courses.user_id = ?
              )
            """,
            (user_id, user_id),
        ).fetchone()
        return total_courses, total_deadlines, completed
    finally:
        connection.close()


def clear_user_data(user_id):
    """Delete only the current user's saved courses and deadlines."""
    _require_user_id(user_id)
    connection = get_connection()
    try:
        connection.execute("BEGIN")
        connection.execute("DELETE FROM deadlines WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM courses WHERE user_id = ?", (user_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
