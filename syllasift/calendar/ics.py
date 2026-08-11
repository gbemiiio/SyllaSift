from datetime import date, datetime, timedelta, timezone


def escape_ics_text(value):
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "\\n")
    return text.replace(";", "\\;").replace(",", "\\,")


def fold_ics_line(line, limit=75):
    parts = []
    remaining = line
    current_limit = limit
    while len(remaining.encode("utf-8")) > current_limit:
        split_at = min(len(remaining), current_limit)
        while len(remaining[:split_at].encode("utf-8")) > current_limit:
            split_at -= 1
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:]
        current_limit = limit - 1
    parts.append(remaining)
    return "\r\n ".join(parts)


def format_timestamp(value):
    if value is None:
        value = datetime.now(timezone.utc)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%dT%H%M%SZ")


def parse_due_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def build_ics_calendar(deadlines, generated_at=None):
    timestamp = format_timestamp(generated_at)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SyllaSift//Course Deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:SyllaSift Deadlines",
    ]
    for deadline in deadlines:
        due_date = parse_due_date(deadline["due_date"])
        end_date = due_date + timedelta(days=1)
        course_label = deadline.get("course_code") or deadline["course_name"]
        summary = f"[{course_label}] {deadline['item']}"
        description = (
            f"Course: {deadline['course_name']}\n"
            f"Term: {deadline['semester']} {deadline['year']}"
        )
        uid = (
            f"course-{deadline['course_id']}-deadline-"
            f"{deadline['deadline_id']}@syllasift.local"
        )
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{timestamp}",
            f"DTSTART;VALUE=DATE:{due_date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end_date:%Y%m%d}",
            f"SUMMARY:{escape_ics_text(summary)}",
            f"DESCRIPTION:{escape_ics_text(description)}",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-P1D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{escape_ics_text(summary)}",
            "END:VALARM",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"
