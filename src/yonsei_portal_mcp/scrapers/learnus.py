"""LearnUs page scrapers.

Each scraper navigates an authenticated :class:`~playwright.async_api.Page` to a
LearnUs URL and extracts structured data via ``page.evaluate`` (running JS in the
real DOM is far more robust than chaining Playwright locators on this Moodle-based
SPA). All selectors below were validated against the live site.

Returned values are plain JSON-serialisable dicts/lists so the MCP layer can hand
them straight back to the model.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from playwright.async_api import Page

LEARNUS_HOME = "https://ys.learnus.org/"
CALENDAR_UPCOMING = "https://ys.learnus.org/calendar/view.php?view=upcoming"
PROGRESS_URL = "https://ys.learnus.org/report/ubcompletion/progress.php?id={course_id}"
COURSE_VIEW_URL = "https://ys.learnus.org/course/view.php?id={course_id}"

KST = timezone(timedelta(hours=9))

# --------------------------------------------------------------------------- #
# JavaScript snippets (run inside the page DOM)
# --------------------------------------------------------------------------- #

_COURSES_JS = r"""
() => {
  const seen = new Set();
  const courses = [];
  document.querySelectorAll('a[href*="/course/view.php?id="]').forEach(a => {
    const m = a.href.match(/id=(\d+)/);
    if (!m) return;
    const id = m[1];
    if (seen.has(id)) return;
    const li = a.closest('li') || a.parentElement;
    if (!li) return;
    const full = (li.innerText || '').replace(/\s+/g, ' ').trim();
    if (!full) return;
    seen.add(id);
    const h = li.querySelector('h3');
    const prog = (full.match(/학습률\s*([\d.]+)\s*%/) || [])[1] || null;
    const att = li.querySelector('a[href*="/report/ubcompletion/progress.php"]');
    courses.push({
      id,
      name: h ? h.textContent.replace(/\s+/g, ' ').trim()
              : a.textContent.replace(/\s+/g, ' ').trim(),
      url: a.href.split('#')[0],
      progress: prog === null ? null : Number(prog),
      attendance_url: att ? att.href : null,
      raw: full,
    });
  });
  return courses;
}
"""

_NOTICES_JS = r"""
() => {
  const seen = new Set();
  const items = [];
  document.querySelectorAll('a[href*="/mod/ubboard/article.php"]').forEach(a => {
    const url = a.href.split('#')[0];
    if (seen.has(url)) return;
    seen.add(url);
    const text = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    items.push({ text, url });
  });
  return items;
}
"""

_NOTICE_BODY_JS = r"""
() => {
  const pick = (sels) => {
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el && (el.innerText || el.textContent || '').trim()) return el;
    }
    return null;
  };
  const titleEl = pick(['.boardTitle', '.ubboard_title', 'h3', 'h2', '.page-header-headings h1']);
  const bodyEl = pick(['.text_to_html', '.boardContent', '.ubboard_content', '#region-main .box', '#region-main']);
  const metaText = (pick(['.boardInfo', '.ubboard_info', '.author']) || {}).innerText || '';
  const dateMatch = metaText.match(/\d{4}[-./]\s?\d{1,2}[-./]\s?\d{1,2}/);
  return {
    title: titleEl ? (titleEl.innerText || titleEl.textContent || '').replace(/\s+/g, ' ').trim() : null,
    author: (metaText.split('\n')[0] || '').replace(/\s+/g, ' ').trim() || null,
    date: dateMatch ? dateMatch[0] : null,
    body: bodyEl ? (bodyEl.innerText || bodyEl.textContent || '').replace(/\n{3,}/g, '\n\n').trim() : null,
  };
}
"""

_CALENDAR_JS = r"""
() => {
  const events = [];
  document.querySelectorAll('[data-region="event-item"]').forEach(ev => {
    const a = ev.querySelector('a[data-action="view-event"]') || ev.querySelector('a[href]');
    const dateEl = ev.querySelector('.date');
    const href = a ? a.href : null;
    const courseM = href ? href.match(/course=(\d+)/) : null;
    const timeM = href ? href.match(/time=(\d+)/) : null;
    events.push({
      title: a ? a.textContent.replace(/\s+/g, ' ').trim()
               : ev.innerText.replace(/\s+/g, ' ').trim(),
      url: href,
      when: dateEl ? dateEl.textContent.replace(/\s+/g, ' ').trim() : null,
      course_id: courseM ? courseM[1] : null,
      epoch: timeM ? Number(timeM[1]) : null,
    });
  });
  return events;
}
"""

_ATTENDANCE_JS = r"""
() => {
  const t = document.querySelector('table.user_progress_table');
  if (!t) return null;
  const rows = [];
  t.querySelectorAll('tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('th,td'))
      .map(c => c.innerText.replace(/\s+/g, ' ').trim());
    if (cells.some(c => c)) rows.push(cells);
  });
  return rows;
}
"""

_MATERIALS_JS = r"""
() => {
  const sections = [];
  const secs = document.querySelectorAll(
    '.course-content li.section, .course-content .section.main, li[id^="section-"]'
  );
  secs.forEach(sec => {
    const nameEl = sec.querySelector('.sectionname, h3.sectionname, .section-title');
    const activities = [];
    sec.querySelectorAll('li.activity').forEach(li => {
      const cls = li.className || '';
      const mod = (cls.match(/modtype_(\w+)/) || [])[1] || null;
      const link = li.querySelector('a[href]');
      // .instancename holds the visible name plus a hidden type label
      // (e.g. "동영상"/"파일") inside .accesshide — strip that for a clean title.
      const inst = li.querySelector('.instancename');
      let title = '';
      let typeLabel = null;
      if (inst) {
        const clone = inst.cloneNode(true);
        const hidden = clone.querySelector('.accesshide');
        if (hidden) {
          typeLabel = (hidden.innerText || hidden.textContent || '')
            .replace(/\s+/g, ' ').trim() || null;
          hidden.remove();
        }
        title = (clone.innerText || clone.textContent || '')
          .replace(/\s+/g, ' ').trim();
      }
      if (!title) {
        title = link
          ? (link.innerText || link.textContent || '').replace(/\s+/g, ' ').trim()
          : '';
      }
      if (!title && !link) return;
      activities.push({
        mod,
        type_label: typeLabel,
        title,
        url: link ? link.href.split('#')[0] : null,
      });
    });
    sections.push({
      id: sec.id || null,
      name: nameEl
        ? (nameEl.innerText || nameEl.textContent || '').replace(/\s+/g, ' ').trim()
        : null,
      activities,
    });
  });
  return sections;
}
"""

# --------------------------------------------------------------------------- #
# Python-side parsing helpers
# --------------------------------------------------------------------------- #

_DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_CODE_RE = re.compile(r"\(([A-Z]{2,}\d[\w.\-()]*)\)")
_COURSE_NOTICE_RE = re.compile(
    r"^\[(?P<course>.+?)\]\s*"
    r"(?P<date>\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일)\s*"
    r"(?P<title>.*)$"
)


def _norm_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def _parse_code_and_professor(raw: str, name: str) -> tuple[Optional[str], Optional[str]]:
    code_m = _CODE_RE.search(name) or _CODE_RE.search(raw)
    code = code_m.group(1) if code_m else None

    professor = None
    if "/" in raw:
        # pattern: "<code> / <professor> 학습률 ..." or "... / <professor> 출석현황"
        m = re.search(r"/\s*([^/]+?)\s*(?:학습률|출석현황|$)", raw)
        if m:
            professor = m.group(1).strip() or None
    return code, professor


def _category(raw: str) -> Optional[str]:
    if "비교과" in raw:
        return "비교과"
    if "교과" in raw:
        return "교과"
    return None


# --------------------------------------------------------------------------- #
# Scrapers
# --------------------------------------------------------------------------- #

async def fetch_courses(page: Page) -> list[dict]:
    """Return the list of the student's enrolled LearnUs courses."""
    await page.goto(LEARNUS_HOME, wait_until="domcontentloaded")
    await page.wait_for_selector(
        'a[href*="/course/view.php?id="]', timeout=15_000
    )
    raw_courses = await page.evaluate(_COURSES_JS)
    courses: list[dict] = []
    for c in raw_courses:
        code, professor = _parse_code_and_professor(c.get("raw", ""), c.get("name", ""))
        courses.append(
            {
                "id": c["id"],
                "name": c["name"],
                "code": code,
                "professor": professor,
                "category": _category(c.get("raw", "")),
                "progress_percent": c.get("progress"),
                "url": c["url"],
                "attendance_url": c.get("attendance_url"),
            }
        )
    return courses


async def _course_name_map(page: Page) -> dict[str, str]:
    try:
        courses = await fetch_courses(page)
    except Exception:
        return {}
    return {c["id"]: c["name"] for c in courses if c.get("id")}


async def fetch_notices(page: Page, scope: str = "all") -> list[dict]:
    """Return LearnUs notices.

    ``scope`` may be ``"all"``, ``"course"`` (only course announcements) or
    ``"platform"`` (only LearnUs platform notices).
    """
    await page.goto(LEARNUS_HOME, wait_until="domcontentloaded")
    await page.wait_for_selector(
        'a[href*="/mod/ubboard/article.php"]', timeout=15_000
    )
    raw_items = await page.evaluate(_NOTICES_JS)

    notices: list[dict] = []
    for item in raw_items:
        text = item["text"].strip()
        url = item["url"]
        m = _COURSE_NOTICE_RE.match(text)
        if m:
            notices.append(
                {
                    "type": "course",
                    "course": m.group("course").strip(),
                    "date": _norm_date(m.group("date")),
                    "title": m.group("title").strip(),
                    "url": url,
                }
            )
        else:
            cleaned = re.sub(r"^공지\s*", "", text)
            date = _norm_date(cleaned)
            title = cleaned
            dm = _DATE_RE.search(cleaned)
            if dm:
                title = cleaned[: dm.start()].strip()
            notices.append(
                {
                    "type": "platform",
                    "course": None,
                    "date": date,
                    "title": title,
                    "url": url,
                }
            )

    if scope in {"course", "platform"}:
        notices = [n for n in notices if n["type"] == scope]
    return notices


def _deadline_kind(title: Optional[str]) -> str:
    """Classify a LearnUs calendar entry by what kind of due date it is.

    The "upcoming" calendar mixes real submissions with auto-generated online
    lecture markers, so callers (and the LLM) must not present them all as
    homework. Returns one of:

    - ``"completion"`` — online course completion marker ("should be completed",
      e.g. 온라인 연구윤리 수료 권장일). Not a submittable assignment.
    - ``"progress"`` — lecture/video viewing cutoff (": Progress stop",
      강의 수강기간 종료). Not a submittable assignment.
    - ``"assignment"`` — a real assignment/activity submission deadline.
    """
    t = (title or "").lower()
    if "should be completed" in t:
        return "completion"
    if "progress stop" in t:
        return "progress"
    return "assignment"


async def fetch_deadlines(
    page: Page,
    course_map: Optional[dict[str, str]] = None,
    course_id: Optional[str] = None,
) -> list[dict]:
    """Return upcoming assignment / activity deadlines from the calendar.

    Each item carries a ``source`` field (DESIGN §4-ter) so callers can tell
    where a deadline came from, plus a ``kind`` field
    (``assignment`` / ``progress`` / ``completion``; see :func:`_deadline_kind`)
    so callers can distinguish real submissions from online-lecture progress or
    completion markers. Items are de-duplicated by ``url`` and sorted by ``due``
    ascending (items without a due time sink to the end). Pass ``course_id`` to
    restrict the result to a single course.
    """
    if course_map is None:
        course_map = await _course_name_map(page)
    await page.goto(CALENDAR_UPCOMING, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)
    raw_events = await page.evaluate(_CALENDAR_JS)

    by_url: dict[str, dict] = {}
    ordered: list[dict] = []
    for e in raw_events:
        epoch = e.get("epoch")
        due_iso = (
            datetime.fromtimestamp(epoch, KST).isoformat() if epoch else None
        )
        cid = e.get("course_id")
        item = {
            "title": e.get("title"),
            "due": due_iso,
            "due_text": e.get("when"),
            "kind": _deadline_kind(e.get("title")),
            "course_id": cid,
            "course": course_map.get(cid) if cid else None,
            "url": e.get("url"),
            "source": "calendar",
        }
        url = item["url"]
        if url:
            if url in by_url:
                continue
            by_url[url] = item
        ordered.append(item)

    if course_id is not None:
        ordered = [d for d in ordered if d.get("course_id") == course_id]

    ordered.sort(key=lambda d: (d.get("due") is None, d.get("due") or ""))
    return ordered


async def fetch_notice_body(page: Page, url: str) -> dict:
    """Return the full text body of a single notice/board article (DESIGN §4-ter).

    The MCP layer hands the body back to the LLM to summarise; we do not
    summarise here. ``url`` must be a LearnUs board article URL as returned by
    :func:`fetch_notices`.
    """
    if "ys.learnus.org" not in url or "/mod/ubboard/article.php" not in url:
        raise ValueError(
            "url 은 fetch_notices 가 돌려준 LearnUs 게시글 주소여야 합니다."
        )
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(500)
    data = await page.evaluate(_NOTICE_BODY_JS)
    return {
        "url": url.split("#")[0],
        "title": (data or {}).get("title"),
        "date": _norm_date((data or {}).get("date")),
        "author": (data or {}).get("author"),
        "body": (data or {}).get("body"),
    }


async def fetch_attendance(page: Page, course_id: str) -> dict:
    """Return the weekly attendance / progress table for one course."""
    await page.goto(
        PROGRESS_URL.format(course_id=course_id), wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(1000)
    rows = await page.evaluate(_ATTENDANCE_JS)
    if not rows:
        return {"course_id": course_id, "header": [], "weeks": []}

    header = rows[0]
    weeks: list[dict] = []
    for row in rows[1:]:
        entry = {}
        for i, value in enumerate(row):
            key = header[i] if i < len(header) and header[i] else f"col{i}"
            entry[key] = value
        weeks.append(entry)
    return {"course_id": course_id, "header": header, "weeks": weeks}


_SECTION_NUM_RE = re.compile(r"section-(\d+)")
_WEEK_NUM_RE = re.compile(r"(\d+)\s*주차")


def _section_week(section: dict) -> Optional[int]:
    """Best-effort week number for a course section (None for the overview)."""
    name = section.get("name") or ""
    m = _WEEK_NUM_RE.search(name)
    if m:
        return int(m.group(1))
    sid = section.get("id") or ""
    m = _SECTION_NUM_RE.search(sid)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    return None


async def fetch_course_materials(page: Page, course_id: str) -> dict:
    """Return the weekly sections and learning materials/activities of a course.

    Navigates to the LearnUs course page and reads each section (강의 개요 +
    weekly blocks) together with its activities (동영상/파일/과제/게시판 등). The
    MCP layer hands this structure to the LLM so it can ground answers (e.g. a
    study checklist) in the *actual* course content rather than guessing.

    ``course_id`` is the id from :func:`fetch_courses`. The returned dict has
    ``course_id``, ``section_count``, ``activity_count`` and ``sections`` (each
    with ``id``, ``week``, ``name`` and a list of ``activities``; every activity
    carries ``type`` (the Moodle module type, e.g. ``vod``/``ubfile``/``assign``),
    ``title`` and ``url``). Sections are ordered by week, with the overview
    (week ``None``) first.
    """
    await page.goto(
        COURSE_VIEW_URL.format(course_id=course_id), wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(1200)
    raw_sections = await page.evaluate(_MATERIALS_JS)

    sections: list[dict] = []
    activity_total = 0
    for sec in raw_sections or []:
        activities = [
            {
                "type": a.get("mod"),
                "title": a.get("title"),
                "url": a.get("url"),
            }
            for a in sec.get("activities", [])
            if a.get("title") or a.get("url")
        ]
        if not activities and not (sec.get("name") or "").strip():
            continue
        activity_total += len(activities)
        sections.append(
            {
                "id": sec.get("id"),
                "week": _section_week(sec),
                "name": sec.get("name"),
                "activities": activities,
            }
        )

    sections.sort(key=lambda s: (s.get("week") is not None, s.get("week") or 0))
    return {
        "course_id": course_id,
        "section_count": len(sections),
        "activity_count": activity_total,
        "sections": sections,
    }
