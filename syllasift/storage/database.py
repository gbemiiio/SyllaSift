import sqlite3


DATABASE_NAME = "SyllaSift.db"


def get_connection():
    return sqlite3.connect(DATABASE_NAME)


def initialize_database():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            course_code TEXT,
            semester TEXT NOT NULL,
            year INTEGER NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS deadlines (
            deadline_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            item TEXT NOT NULL,
            raw_date TEXT,
            due_date TEXT NOT NULL,
            is_completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
        """
    )
    connection.commit()
    connection.close()


def save_course(course_name, course_code, semester, year):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO courses (course_name, course_code, semester, year)
        VALUES (?, ?, ?, ?)
        """,
        (course_name, course_code, semester, year),
    )
    course_id = cursor.lastrowid
    connection.commit()
    connection.close()
    return course_id


def save_deadlines(course_id, table_rows):
    connection = get_connection()
    cursor = connection.cursor()
    for row in table_rows:
        cursor.execute(
            """
            INSERT INTO deadlines (
                course_id, item, raw_date, due_date, is_completed, completed_at
            )
            VALUES (?, ?, ?, ?, 0, NULL)
            """,
            (
                course_id,
                row["Item"],
                row["Date"],
                row["Normalized Date"],
            ),
        )
    connection.commit()
    connection.close()


def get_course_options():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "SELECT course_id, course_name FROM courses ORDER BY course_name"
    )
    courses = cursor.fetchall()
    connection.close()
    return courses


def get_courses_for_export():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT course_id, course_name, course_code, semester, year
        FROM courses
        ORDER BY year, semester, course_code, course_name
        """
    )
    courses = [
        {
            "course_id": row[0],
            "course_name": row[1],
            "course_code": row[2],
            "semester": row[3],
            "year": row[4],
        }
        for row in cursor.fetchall()
    ]
    connection.close()
    return courses


def get_deadlines_for_export(course_ids):
    if not course_ids:
        return []

    normalized_ids = [int(course_id) for course_id in course_ids]
    placeholders = ", ".join("?" for _ in normalized_ids)
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
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
        JOIN courses AS c ON c.course_id = d.course_id
        WHERE c.course_id IN ({placeholders}) AND d.is_completed = 0
        ORDER BY d.due_date, c.course_code, c.course_name, d.item
        """,
        normalized_ids,
    )
    deadlines = [
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
        for row in cursor.fetchall()
    ]
    connection.close()
    return deadlines


def get_deadlines(course_id):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            deadline_id,
            course_id,
            item,
            raw_date,
            due_date,
            is_completed,
            created_at,
            completed_at
        FROM deadlines
        WHERE course_id = ?
        ORDER BY due_date
        """,
        (course_id,),
    )
    deadlines = cursor.fetchall()
    connection.close()
    return deadlines


def update_deadline_status(deadline_id, is_completed):
    connection = get_connection()
    cursor = connection.cursor()
    if is_completed:
        cursor.execute(
            """
            UPDATE deadlines
            SET is_completed = 1, completed_at = CURRENT_TIMESTAMP
            WHERE deadline_id = ?
            """,
            (deadline_id,),
        )
    else:
        cursor.execute(
            """
            UPDATE deadlines
            SET is_completed = 0, completed_at = NULL
            WHERE deadline_id = ?
            """,
            (deadline_id,),
        )
    connection.commit()
    connection.close()


def get_dashboard_stats():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM courses")
    total_courses = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM deadlines")
    total_deadlines = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM deadlines WHERE is_completed = 1")
    completed = cursor.fetchone()[0]
    connection.close()
    return total_courses, total_deadlines, completed


def clear_all_data():
    """Delete all saved data while preserving the database schema."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM deadlines")
        cursor.execute("DELETE FROM courses")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
