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
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..errors import ScrapeFailedError

LEARNUS_HOME = "https://ys.learnus.org/"
CALENDAR_UPCOMING = "https://ys.learnus.org/calendar/view.php?view=upcoming"
PROGRESS_URL = "https://ys.learnus.org/report/ubcompletion/progress.php?id={course_id}"
COURSE_VIEW_URL = "https://ys.learnus.org/course/view.php?id={course_id}"

KST = timezone(timedelta(hours=9))

# --------------------------------------------------------------------------- #
# JavaScript snippets (run inside the page DOM)
# --------------------------------------------------------------------------- #

_KOREAN_JS = r"() => /^ko(?:-|$)/i.test(document.documentElement.lang)"

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
    const dateMatch = metaText.match(/(?<!\d)\d{4}([-./])\s*\d{1,2}\1\s*\d{1,2}(?!\d)/);
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
    if (events.length) return events;
    const normalize = text => text.replace(/\s+/g, ' ').trim();
    const marker = document.querySelector('.maincalendar .eventlist .calendar-no-results');
    if (marker && marker.getClientRects().length &&
            normalize(marker.innerText || '') === '계획된 일정이 없습니다.') return [];
    const main = document.querySelector('#region-main');
    const emptyText = globalThis.M?.str?.calendar?.noupcomingevents;
    if (main && typeof emptyText === 'string' && emptyText.trim()) {
        const elements = [main, ...main.querySelectorAll('*')];
        if (elements.some(el => el.getClientRects().length &&
                normalize(el.innerText || '') === normalize(emptyText))) return [];
    }
    return null;
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
    return rows.length ? rows : null;
}
"""

_MATERIALS_JS = r"""
() => {
  const sections = [];
  const secs = document.querySelectorAll(
    '.course-content li.section, .course-content .section.main, li[id^="section-"]'
  );
    if (!secs.length) return null;
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
_NUMERIC_DATE_RE = re.compile(r"(?<!\d)(\d{4})([-./])\s*(\d{1,2})\2\s*(\d{1,2})(?!\d)")
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
    if m:
        parts = m.groups()
    else:
        m = _NUMERIC_DATE_RE.search(text)
        if not m:
            return None
        parts = m.group(1, 3, 4)
    try:
        return datetime(*(int(part) for part in parts)).date().isoformat()
    except ValueError:
        return None


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


def _korean_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "lang"]
    return urlunsplit(parts._replace(query=urlencode([*query, ("lang", "ko")]), fragment=""))


def _require_page_url(actual_url: str, expected_url: str, alternate_paths: tuple[str, ...] = ()) -> None:
    try:
        actual = urlsplit(actual_url)
        expected = urlsplit(expected_url)
        query = parse_qs(actual.query, keep_blank_values=True)
        valid = (
            actual.scheme == expected.scheme
            and actual.hostname == expected.hostname
            and actual.port in (None, 443)
            and not actual.username and not actual.password
            and actual.path in (expected.path, *alternate_paths)
            and all(query.get(key) == value for key, value in parse_qs(expected.query, keep_blank_values=True).items() if key != "lang")
        )
    except ValueError:
        valid = False
    if not valid:
        raise ScrapeFailedError("요청한 LearnUs 페이지에 도착하지 못했습니다.")


async def _goto_korean(page: Page, url: str, *, alternate_paths: tuple[str, ...] = ()) -> None:
    response = await page.goto(_korean_url(url), wait_until="domcontentloaded")
    if response is not None and not response.ok:
        raise ScrapeFailedError("LearnUs 페이지 요청에 실패했습니다.")
    _require_page_url(page.url, url, alternate_paths)
    try:
        await page.wait_for_function(_KOREAN_JS, timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise ScrapeFailedError("LearnUs 페이지의 한국어 표시를 확인하지 못했습니다.") from exc
    _require_page_url(page.url, url, alternate_paths)


async def _read_ready_page(page: Page, url: str, script: str, *, alternate_paths: tuple[str, ...] = ()) -> list:
    await _goto_korean(page, url, alternate_paths=alternate_paths)
    try:
        await page.wait_for_function(f"() => ({script})() !== null", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise ScrapeFailedError("LearnUs 페이지의 결과 구조를 확인하지 못했습니다.") from exc
    _require_page_url(page.url, url, alternate_paths)
    result = await page.evaluate(script)
    if not isinstance(result, list):
        raise ScrapeFailedError("LearnUs 페이지의 결과 구조를 확인하지 못했습니다.")
    return result


# --------------------------------------------------------------------------- #
# Scrapers
# --------------------------------------------------------------------------- #

async def fetch_courses(page: Page) -> list[dict]:
    """Return the list of the student's enrolled LearnUs courses."""
    await _goto_korean(page, LEARNUS_HOME)
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
    await _goto_korean(page, LEARNUS_HOME)
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
    raw_events = await _read_ready_page(page, CALENDAR_UPCOMING, _CALENDAR_JS)

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
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        valid = (
            parts.scheme == "https" and parts.hostname == "ys.learnus.org"
            and parts.path == "/mod/ubboard/article.php" and parts.port in (None, 443)
            and not parts.username and not parts.password
            and len(query.get("id", [])) == 1
            and re.fullmatch(r"[0-9]{1,20}", query["id"][0])
            and ("bwid" not in query or (
                len(query["bwid"]) == 1 and re.fullmatch(r"[0-9]{1,20}", query["bwid"][0])
            ))
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "url 은 fetch_notices 가 돌려준 LearnUs 게시글 주소여야 합니다."
        )
    await _goto_korean(page, url)
    await page.wait_for_timeout(500)
    _require_page_url(page.url, url)
    data = await page.evaluate(_NOTICE_BODY_JS)
    return {
        "url": _korean_url(url),
        "title": (data or {}).get("title"),
        "date": _norm_date((data or {}).get("date")),
        "author": (data or {}).get("author"),
        "body": (data or {}).get("body"),
    }


async def fetch_attendance(page: Page, course_id: str) -> dict:
    """Return the weekly attendance / progress table for one course."""
    if not re.fullmatch(r"[0-9]{1,20}", course_id):
        raise ValueError("course_id는 본인 강좌 목록의 숫자 ID여야 합니다.")
    rows = await _read_ready_page(
        page, PROGRESS_URL.format(course_id=course_id), _ATTENDANCE_JS,
        alternate_paths=("/report/ubcompletion/user_progress_a.php",),
    )
    if not rows:
        raise ScrapeFailedError("LearnUs 출석현황 표를 확인하지 못했습니다.")

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
    if not re.fullmatch(r"[0-9]{1,20}", course_id):
        raise ValueError("course_id는 본인 강좌 목록의 숫자 ID여야 합니다.")
    raw_sections = await _read_ready_page(
        page, COURSE_VIEW_URL.format(course_id=course_id), _MATERIALS_JS
    )

    sections: list[dict] = []
    activity_total = 0
    for sec in raw_sections:
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


def assignments_from_materials(materials: dict) -> dict:
    """Select assignment links without treating videos or quizzes as submissions."""
    sections = materials.get("sections")
    if not isinstance(sections, list):
        raise ScrapeFailedError("LearnUs 강의자료 목록 구조를 확인하지 못했습니다.")
    assignments = []
    for section in sections:
        activities = section.get("activities")
        if not isinstance(activities, list):
            raise ScrapeFailedError("LearnUs 학습활동 목록 구조를 확인하지 못했습니다.")
        for activity in activities:
            if not isinstance(activity, dict) or not isinstance(activity.get("type"), str) or not re.fullmatch(r"[a-z][a-z0-9_]*", activity["type"]):
                raise ScrapeFailedError("LearnUs 학습활동 유형을 확인하지 못했습니다.")
            if activity.get("type") == "assign":
                if not all(isinstance(activity.get(key), str) and activity[key].strip() for key in ("title", "url")):
                    raise ScrapeFailedError("LearnUs 과제 제목 또는 링크를 확인하지 못했습니다.")
                assignments.append({
                    "title": activity.get("title"),
                    "url": activity.get("url"),
                    "week": section.get("week"),
                    "section": section.get("name"),
                })
    return {
        "course_id": materials["course_id"],
        "count": len(assignments),
        "assignments": assignments,
    }


def parse_course_history(html: str) -> dict:
    """Read the course-history table, never a navigation/sidebar course list."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.table-coursemos")
    if table is None:
        raise ScrapeFailedError("LearnUs 과거강좌 표를 확인하지 못했습니다.")
    headers = [cell.get_text(strip=True) for cell in table.select("th")]
    if headers != ["연도", "학기", "강좌명"]:
        raise ScrapeFailedError("LearnUs 과거강좌 열 구성이 변경되었습니다.")
    rows = table.select("tbody tr")
    if not rows:
        raise ScrapeFailedError("LearnUs 과거강좌 결과 상태가 확인되지 않았습니다.")
    courses = []
    course_ids = set()
    for row in rows:
        cells = row.find_all("td", recursive=False)
        if len(rows) == 1 and len(cells) == 1 and cells[0].get("colspan") == "3" and cells[0].get_text(strip=True) == "참여중인 강좌가 없습니다.":
            break
        if len(cells) != 3:
            raise ScrapeFailedError("LearnUs 과거강좌 행 구조가 변경되었습니다.")
        link = cells[2].select_one('a[href]')
        if link is None:
            raise ScrapeFailedError("LearnUs 과거강좌 링크가 없습니다.")
        url = urlsplit(urljoin(LEARNUS_HOME, str(link["href"])))
        course_id = parse_qs(url.query).get("id", [""])[0]
        if url.scheme != "https" or url.hostname != "ys.learnus.org" or url.path != "/course/view.php" or url.username or url.password or url.port not in (None, 443) or not re.fullmatch(r"[0-9]+", course_id):
            raise ScrapeFailedError("LearnUs 과거강좌 링크를 확인하지 못했습니다.")
        if course_id in course_ids:
            raise ScrapeFailedError("LearnUs 과거강좌 ID가 중복되었습니다.")
        course_ids.add(course_id)
        courses.append({
            "year": cells[0].get_text(strip=True), "semester": cells[1].get_text(strip=True),
            "name": link.get_text(" ", strip=True), "id": course_id,
            "url": COURSE_VIEW_URL.format(course_id=course_id),
        })
    return {
        "count": len(courses), "courses": courses,
        "has_pagination": bool(soup.select('.pagination,.paging,[rel="next"],[rel="prev"],[name="page"],a[href*="page="]')),
    }


async def fetch_course_history(
    browser_page: Page,
    year: Optional[int] = None,
    semester: str = "all",
    page: int = 1,
) -> dict:
    """Read the displayed result after verifying selected filters and row terms.

    Year/semester filters are GET form fields. No page parameter is sent to
    LearnUs, and later pages are rejected until a real affordance is verified.
    The history view can include current enrollments, not only past courses.
    Neither filter verification nor absent paging proves systemwide completeness.
    """
    if type(page) is not int or not 1 <= page <= 100:
        raise ValueError("page는 1부터 100까지의 정수여야 합니다.")
    if page != 1:
        raise ValueError("LearnUs 강좌 이력의 페이지 이동 기능이 확인되지 않아 page=1만 지원합니다.")
    if year is not None and not 2003 <= year <= datetime.now(KST).year:
        raise ValueError("year는 2003년부터 현재 연도까지입니다.")
    if semester not in {"all", "10", "11", "20", "21"}:
        raise ValueError("semester는 all/10(1학기)/11(여름)/20(2학기)/21(겨울)입니다.")
    query = urlencode({"year": year if year is not None else "all", "semester": semester})
    url = _korean_url(LEARNUS_HOME + "local/ubion/user/index.php?" + query)
    await _goto_korean(browser_page, url)
    await browser_page.wait_for_selector("table.table-coursemos tbody tr", timeout=15_000)
    _require_page_url(browser_page.url, url)
    selected = await browser_page.evaluate("""() => {
        const years = document.querySelectorAll('select[name="year"]');
        const semesters = document.querySelectorAll('select[name="semester"]');
        if (years.length !== 1 || semesters.length !== 1) return null;
        const year = years[0], semester = semesters[0];
        if (year.disabled || semester.disabled || year.selectedOptions.length !== 1 ||
                semester.selectedOptions.length !== 1 || year.selectedOptions[0].disabled ||
                semester.selectedOptions[0].disabled) return null;
        return {year: year.value, semester: semester.value,
            semester_label: semester.selectedOptions[0].textContent.trim()};
    }""")
    if not isinstance(selected, dict) or selected.get("year") != str(year if year is not None else "all") or selected.get("semester") != semester or not selected.get("semester_label"):
        raise ScrapeFailedError("LearnUs 강좌 이력의 선택된 연도/학기 필터를 확인하지 못했습니다.")
    result = parse_course_history(await browser_page.content())
    if result["has_pagination"]:
        raise ScrapeFailedError("LearnUs 강좌 이력에 검증되지 않은 페이지 이동 구조가 나타났습니다.")
    if any(
        (year is not None and course["year"] != str(year))
        or (semester != "all" and course["semester"] != selected["semester_label"])
        for course in result["courses"]
    ):
        raise ScrapeFailedError("LearnUs 강좌 이력의 표시된 행이 선택한 연도/학기 필터와 다릅니다.")
    result.update(
        year=year, semester=semester, page=page, next_page=None, has_next=None,
        pagination_supported=False, scope="displayed_result", filters_verified=True,
        scope_note="선택된 연도/학기 필터와 행의 일치를 확인한 표시 결과이며 현재 수강 강좌가 포함될 수 있습니다. count는 표시된 강좌 수입니다. 페이지 이동 UI가 없다는 관찰은 전체 이력의 완전성이나 다음 결과의 부재를 보장하지 않으며 page=1은 내부 호환값입니다.",
        source_url=browser_page.url, fetched_at=datetime.now(KST).isoformat(),
    )
    return result


def parse_assignment_status(html: str, assignment_id: str) -> dict:
    """Read independent submission/grading states, excluding submitted content."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".submissionstatustable")
    if table is not None and table.name != "table":
        table = table.select_one("table")
    if table is None:
        raise ScrapeFailedError("LearnUs 과제 제출상태 표를 확인하지 못했습니다.")
    fields = {}
    for row in table.select(":scope > tr, :scope > tbody > tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) != 2:
            raise ScrapeFailedError("LearnUs 과제 제출상태 열 구성이 변경되었습니다.")
        label = cells[0].get_text(" ", strip=True)
        if label in fields:
            raise ScrapeFailedError("LearnUs 과제 제출상태 항목이 중복되었습니다.")
        fields[label] = cells[1]
    if "제출 여부" not in fields:
        raise ScrapeFailedError("LearnUs 과제 제출 여부를 확인하지 못했습니다.")

    def text(label):
        return fields[label].get_text(" ", strip=True) if label in fields else None

    raw_status = text("제출 여부")
    status = {
        "제출 안 함": "not_submitted", "제출 완료": "submitted",
        "제출됨": "submitted", "초안(미제출)": "draft",
    }.get(raw_status, "unknown")
    due_raw = text("종료 일시")
    due = None
    if due_raw and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", due_raw):
        try:
            due = datetime.strptime(due_raw, "%Y-%m-%d %H:%M").replace(tzinfo=KST).isoformat()
        except ValueError:
            pass
    title = soup.select_one("h2")
    return {
        "assignment_id": assignment_id,
        "title": title.get_text(" ", strip=True) if title else None,
        "submission_status": status, "submission_status_raw": raw_status,
        "grading_status_raw": text("채점 상황"), "due": due, "due_raw": due_raw,
        "remaining_raw": text("마감까지 남은 기한"),
        "overdue_marker": bool(table.select_one(".overdue")),
        "last_modified_raw": text("최종 수정 일시"),
        "url": LEARNUS_HOME + "mod/assign/view.php?id=" + assignment_id,
    }


async def fetch_assignment_status(page: Page, assignment_id: str) -> dict:
    if not re.fullmatch(r"[0-9]{1,20}", assignment_id):
        raise ValueError("assignment_id는 과제 URL의 숫자 id여야 합니다.")
    await _goto_korean(page, LEARNUS_HOME + "mod/assign/view.php?" + urlencode({"id": assignment_id}))
    await page.wait_for_selector(".submissionstatustable", timeout=15_000)
    _require_page_url(page.url, LEARNUS_HOME + "mod/assign/view.php?id=" + assignment_id)
    result = parse_assignment_status(await page.content(), assignment_id)
    result["fetched_at"] = datetime.now(KST).isoformat()
    return result


def parse_gradebook(html: str, course_id: str, include_feedback: bool = False) -> dict:
    """Read displayed Moodle grade rows without inferring missing grades or totals."""
    table = BeautifulSoup(html, "html.parser").select_one("table.user-grade")
    columns = {
        "column-grade": "grade_raw", "column-weight": "weight_raw",
        "column-range": "range_raw", "column-percentage": "percentage_raw",
        "column-contributiontocoursetotal": "contribution_raw",
        "column-feedback": "feedback",
    }
    if table is None or not table.select_one("thead .column-itemname") or not table.select_one("thead .column-grade"):
        raise ScrapeFailedError("LearnUs 성적부 표와 성적 열을 확인하지 못했습니다.")
    active_columns = [column for column in columns if table.select_one("thead ." + column)]

    def is_hidden(element):
        return (
            element.has_attr("hidden")
            or bool(set(element.get("class", [])) & {"hidden", "d-none", "accesshide"})
            or bool(re.search(
                r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!important\s*)?(?:;|$)",
                element.get("style", ""), re.IGNORECASE,
            ))
        )

    def visible_text(cell):
        if is_hidden(cell):
            return None
        copy = BeautifulSoup(str(cell), "html.parser")
        for element in reversed(copy.find_all(True)):
            if element.name in {"script", "style"} or is_hidden(element):
                element.decompose()
        return " ".join(copy.get_text(" ", strip=True).split())

    items = []
    for row in table.select(":scope > tbody > tr"):
        if any(is_hidden(element) for element in [row, *row.parents]):
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        name_cells = [cell for cell in cells if "column-itemname" in cell.get("class", [])]
        if len(name_cells) != 1 or not visible_text(name_cells[0]):
            raise ScrapeFailedError("LearnUs 성적 항목명을 확인하지 못했습니다.")
        item = {"name": visible_text(name_cells[0])}
        data_cells = [cell for cell in cells if "column-grade" in cell.get("class", [])]
        if not data_cells:
            if not str(name_cells[0].get("colspan", "")).isdigit() or int(name_cells[0]["colspan"]) <= 1:
                raise ScrapeFailedError("LearnUs 성적 항목의 점수 열이 없습니다.")
            item.update(kind="category", grade_raw=None, grade_available=False)
        else:
            item["kind"] = "total" if any("baggt" in cell.get("class", []) for cell in cells) else "item"
            for column in active_columns:
                matches = [cell for cell in cells if column in cell.get("class", [])]
                if len(matches) != 1:
                    raise ScrapeFailedError("LearnUs 성적부의 행과 열 구성이 다릅니다.")
                if column != "column-feedback" or include_feedback:
                    item[columns[column]] = visible_text(matches[0])
            item["grade_available"] = item["grade_raw"] not in {None, "", "-", "숨김", "비공개"}
        items.append(item)
    if not items:
        raise ScrapeFailedError("LearnUs 성적부의 표시 항목을 확인하지 못했습니다. 0점을 의미하지 않습니다.")
    return {
        "course_id": course_id, "count": len(items), "items": items,
        "feedback_included": include_feedback,
        "note": "LMS 표시 성적이며 ERP 확정 성적과 다릅니다. category는 분류, total은 소계/총계 행이므로 항목과 중복 합산하지 마세요. '-'·숨김은 0점이 아닙니다.",
    }


async def fetch_gradebook(page: Page, course_id: str, include_feedback: bool = False) -> dict:
    if not re.fullmatch(r"[0-9]{1,20}", course_id):
        raise ValueError("course_id는 본인 강좌 목록의 숫자 ID여야 합니다.")
    url = _korean_url(LEARNUS_HOME + "grade/report/user/index.php?" + urlencode({"id": course_id}))
    await _goto_korean(page, url)
    await page.wait_for_selector("table.user-grade", timeout=15_000)
    _require_page_url(page.url, url)
    result = parse_gradebook(await page.content(), course_id, include_feedback)
    result.update(source_url=url, fetched_at=datetime.now(KST).isoformat())
    return result
