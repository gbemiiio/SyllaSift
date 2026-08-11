DATE_PATTERN = (
    r"\b(?:January|Jan\.?|February|Feb\.?|March|Mar\.?|April|Apr\.?|"
    r"May|June|Jun\.?|July|Jul\.?|August|Aug\.?|September|Sept\.?|"
    r"Sep\.?|October|Oct\.?|November|Nov\.?|December|Dec\.?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s+\d{4})?\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b\d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b"
)
DAY_FIRST_DATE_PATTERN = (
    r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\.?(?:\s+\d{4})?\b"
)
COURSE_CODE_PATTERN = r"\b[A-Z]{2,5}\s*-?\s*\d{3,4}[A-Z]?\b"
TERM_PATTERN = r"\b(Spring|Summer|Fall|Autumn|Winter)\s+(20\d{2})\b"
WEEKDAY_PATTERN = (
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
)
ASSESSMENT_WORDS = [
    "assignment", "homework", "quiz", "exam", "midterm", "final",
    "project", "paper", "presentation", "test", "lab", "report",
    "proposal", "demo", "reflection", "log", "extra credit", "syllabus",
    "class work", "peer review", "pitch", "spotlight",
]
EXCLUDED_CONTEXTS = [
    "course policy", "attendance", "absence", "religious holiday",
    "accommodation", "notify your instructor", "instructor notice", "cios",
    "office hours", "regrade", "rubric", "deduction", "grade breakdown",
    "testing center", "starting the week", "specific dates", "makeup exam",
    "makeup quiz", "course calendar", "registrar", "conflict period",
    "general information", "no class", "review session", "exam review",
    "q&a session", "debrief", "progress report", "withdraw", "make-up",
    "makeup", "grades will be", "scheduled on the following",
]
EXCLUDED_HEADINGS = [
    "attendance", "accommodations", "religious holidays", "regrade requests",
    "makeup quizzes and exams", "office hours", "general information",
]
