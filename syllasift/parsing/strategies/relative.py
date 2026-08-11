import re


def word_to_number(value):
    values = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
    }
    return int(value) if value.isdigit() else values.get(value.lower(), 0)


def extract_relative_deadlines(text, candidates):
    generated = []
    exams = {}

    for candidate in candidates:
        match = re.fullmatch(
            r"Exam\s*#?\s*(\d+)(?:\s+.*)?",
            candidate["Item"],
            re.IGNORECASE,
        )
        if match:
            exams[int(match.group(1))] = candidate["Normalized Date"]

    homework_match = re.search(
        r"(?:There are\s+)?(\d+|one|two|three|four|five|six)\s+sets?\s+of\s+homework"
        r".*?corresponding\s+to\s+the\s+(?:\w+\s+)?exams?",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if homework_match:
        count = word_to_number(homework_match.group(1))
        for number in range(1, count + 1):
            if number in exams:
                generated.append(
                    {
                        "Item": f"Homework Set {number}",
                        "Date": exams[number],
                        "Normalized Date": exams[number],
                    }
                )

    submission_match = re.search(
        r"(\d+|one|two|three|four|five|six)\s+submissions?.{0,160}?"
        r"due\s+on\s+each\s+exam\s+day",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if submission_match:
        count = word_to_number(submission_match.group(1))
        prefix_text = text[:submission_match.start()]
        headings = re.findall(
            r"^\s*([A-Z][A-Z\- ]{4,})\s*$",
            prefix_text,
            re.MULTILINE,
        )
        label = headings[-1].title() if headings else "Project Submission"
        for number in range(1, count + 1):
            if number in exams:
                generated.append(
                    {
                        "Item": f"{label} {number}",
                        "Date": exams[number],
                        "Normalized Date": exams[number],
                    }
                )

    return generated
