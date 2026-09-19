import os
import time
import requests
import threading  # Added for thread-safe file writing
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# env config
load_dotenv()

REQUIRED_ENV_VARS = (
    "SESSION_ID",
    "CSRFTOKEN",
    "NEXT_AUTH_SESSION_TOKEN",
    "CATEGORY_ID",
    "SUBCATEGORY_ID",
    "MAX_CONCURRENT_COURSES",
)

missing = [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]
if missing:
    raise SystemExit(
        "Missing env vars: " + ", ".join(missing) + ". Copy .env.example to .env and fill them in."
    )

try:
    MAX_CONCURRENT_COURSES = int(os.getenv("MAX_CONCURRENT_COURSES"))
except ValueError:
    raise SystemExit("MAX_CONCURRENT_COURSES must be an integer.")

SESSION_ID = os.getenv("SESSION_ID")
CSRFTOKEN = os.getenv("CSRFTOKEN")
NEXT_AUTH_SESSION_TOKEN = os.getenv("NEXT_AUTH_SESSION_TOKEN")
CATEGORY_ID = os.getenv("CATEGORY_ID")
SUBCATEGORY_ID = os.getenv("SUBCATEGORY_ID")

# File to track completed courses
COMPLETED_COURSES_FILE = "completed_courses.txt"
INPUT_REQUIRED_LINKS_FILE = "input_required_links.txt"
file_lock = threading.Lock()

def setup_driver():
    browser = os.getenv("BROWSER", "chrome").lower()
    if browser == "firefox":
        options = webdriver.FirefoxOptions()
    elif browser == "chromium":
        options = webdriver.ChromeOptions()
    else:
        raise SystemExit("BROWSER must be one of: chrome, brave, firefox")

    browser_binary = os.getenv("BROWSER_BINARY")
    if browser_binary:
        options.binary_location = os.path.expanduser(browser_binary)

    options.add_argument("--start-maximized")
    options.page_load_strategy = "eager"
    # options.add_argument("--headless=new")
    if browser != "firefox":
        options.add_argument("--disable-gpu")
    driver = webdriver.Firefox(options=options) if browser == "firefox" else webdriver.Chrome(options=options)
    driver.set_script_timeout(60)
    return driver

def inject_session_cookies(driver, domain_url):
    driver.get(domain_url)    
    driver.delete_all_cookies()
    driver.add_cookie({
        'name': 'sessionid',
        'value': SESSION_ID,
        'path': '/',
        'secure': True,
        'httpOnly': True
    })
    driver.add_cookie({
        'name': 'csrftoken',
        'value': CSRFTOKEN,
        'path': '/',
        'secure': True
    })

def load_completed_courses():
    """Reads already finished course IDs from the text file."""
    if not os.path.exists(COMPLETED_COURSES_FILE):
        return set()
    with open(COMPLETED_COURSES_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_completed_course(course_id):
    """Thread-safely appends a successfully completed course ID to the text file."""
    with file_lock:
        with open(COMPLETED_COURSES_FILE, "a") as f:
            f.write(f"{course_id}\n")
    print(f"[+] [SAVED] Course ID {course_id} written to {COMPLETED_COURSES_FILE}")

def save_input_required_link(course_id, page_url, page_title, input_count):
    """Appends pages containing manual-answer inputs without affecting course completion."""
    record = f"{course_id}\t{page_title}\t{input_count} input(s)\t{page_url}\n"
    with file_lock:
        existing = set()
        if os.path.exists(INPUT_REQUIRED_LINKS_FILE):
            with open(INPUT_REQUIRED_LINKS_FILE, "r", encoding="utf-8") as file:
                existing = set(file)
        if record not in existing:
            with open(INPUT_REQUIRED_LINKS_FILE, "a", encoding="utf-8") as file:
                file.write(record)
    print(f"[!] [INPUT REQUIRED] {page_title}: {page_url}")

def fetch_and_enroll_all_courses():
    session = requests.Session()
    session.cookies.set("sessionid", SESSION_ID, domain="bpkpenaburdigilearn.or.id")
    session.cookies.set("csrftoken", CSRFTOKEN, domain="bpkpenaburdigilearn.or.id")
    session.cookies.set("next-auth.session-token", NEXT_AUTH_SESSION_TOKEN, domain="cms.bpkpenaburdigilearn.or.id")
    headers = {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRFTOKEN,
        "Referer": "https://bpkpenaburdigilearn.or.id/"
    }
    
    print("[+] Visiting homepage: https://bpkpenaburdigilearn.or.id")
    try:
        session.get("https://bpkpenaburdigilearn.or.id", headers=headers, timeout=10)
    except Exception as e:
        print(f"[!] Homepage request failed: {e}")

    course_ids = []
    page = 1
    
    while True:
        print(f"[+] Requesting API search data for page {page}...")
        search_url = "https://cms.bpkpenaburdigilearn.or.id/api/courses/search"
        payload = {
            "q": "",
            "category": CATEGORY_ID,
            "subCategory": SUBCATEGORY_ID,
            "page": page,
            "sortBy": "latest",
            "tag": ""
        }
        
        try:
            res = session.post(search_url, json=payload, headers=headers, timeout=15)
            if res.status_code != 200:
                print(f"[!] API Search returned bad status code: {res.status_code}")
                break
                
            data = res.json()
            docs = data.get("docs", [])
            
            if not docs:
                print("[+] No more courses found. Ending search loop.")
                break
                
            print(f"[+] Found {len(docs)} courses on page {page}.")
            for course in docs:
                c_id = course.get("id")
                c_name = course.get("name", "Unknown")
                is_enrolled = course.get("isEnrolled", False)
                course_ids.append(c_id)
                
                if not is_enrolled:                    
                    enroll_url = "https://cms.bpkpenaburdigilearn.or.id/api/enrollment/"
                    enroll_payload = {
                        "course": c_id
                    }              
                    try:
                        enroll_res = session.post(enroll_url, json=enroll_payload, headers=headers, timeout=10)
                        print(f"[-] [ENROLL] API Response Status: {enroll_res.status_code}")
                        
                        if enroll_res.status_code == 400:
                            print("[-] [ENROLL] Status 400 detected. Retrying with explicit string payload conversion...")
                            import json
                            enroll_res = session.post(enroll_url, data=json.dumps(enroll_payload), headers=headers, timeout=10)
                            print(f"[-] [ENROLL] Retry API Response Status: {enroll_res.status_code}")
                            
                    except Exception as enroll_err:
                        print(f"[!] [ENROLL] Request error for {c_id}: {enroll_err}")
                else:
                    print(f"[+] [SKIP ENROLL] Course '{c_name}' is already enrolled.")
            page += 1
            time.sleep(1)
            
        except Exception as err:
            print(f"[!] Critical error during search iteration: {err}")
            break
            
    return list(set(course_ids))

def collect_subsection_urls(driver, base_url):
    print(f"[>] Loading course structure index from: {base_url}")
    driver.get(base_url)
    WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.subsection-text"))
    )
    subsections = driver.find_elements(By.CSS_SELECTOR, "a.subsection-text")
    
    urls = []
    for sub in subsections:
        href = sub.get_attribute("href")
        if not href:
            continue
        is_done = sub.find_elements(By.CSS_SELECTOR, "span.complete-checkmark")
        if is_done:
            continue
        else:
            urls.append(href)
    print(f"[>] Found {len(urls)} active uncompleted subsections inside this course.")
    return urls

def automate_video_component(session, driver):
    print("    [~] Running embedded bunnynet tracking via direct requests...")
    # Extract courseId, usageId, and duration from the page via a small JS helper
    try:
        js = r"""
        return (function(){
            const videoBlock = document.querySelector('[data-block-type="bunnynet"]');
            if (!videoBlock) return null;
            const courseId = videoBlock.getAttribute('data-course-id');
            const usageId = videoBlock.getAttribute('data-usage-id');
            const scripts = videoBlock.querySelectorAll('script');
            let videoMetadata = {};
            for (const s of scripts) {
                if (s.textContent && s.textContent.includes('current_time')) {
                    try {
                        const match = s.textContent.match(/\{.*"current_time".*\}/);
                        if (match) { videoMetadata = JSON.parse(match[0]); break; }
                    } catch(e) {}
                }
            }
            const duration = videoMetadata.duration || videoMetadata.current_time || 600;
            return {courseId: courseId, usageId: usageId, duration: duration};
        })();
        """
        info = driver.execute_script(js)
    except Exception as e:
        print(f"    [!] Failed to extract video metadata via JS: {e}")
        info = None

    if not info:
        print("    [!] No video block metadata found; skipping direct request approach.")
        return

    try:
        course_id = info.get('courseId')
        usage_id = info.get('usageId')
        duration = int(info.get('duration') or 600)

        total_chunks = (duration + 9) // 10
        watched_chunks = list(range(1, total_chunks + 1))

        track_url = f"https://lms.bpkpenaburdigilearn.or.id/courses/{course_id}/xblock/{usage_id}/handler/track_watch"
        publish_url = f"https://lms.bpkpenaburdigilearn.or.id/courses/{course_id}/xblock/{usage_id}/handler/publish_completion"

        headers = {
            "Content-Type": "application/json",
            "X-CSRFToken": CSRFTOKEN,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://lms.bpkpenaburdigilearn.or.id/courses/{course_id}/xblock/{usage_id}"
        }

        track_payload = {"duration": duration, "watched_chunks": watched_chunks}
        r1 = session.post(track_url, json=track_payload, headers=headers, timeout=10)
        print(f"    [~] track_watch -> {r1.status_code} {r1.text[:200]}")

        publish_payload = {"completion": 1}
        r2 = session.post(publish_url, json=publish_payload, headers=headers, timeout=10)
        print(f"    [~] publish_completion -> {r2.status_code} {r2.text[:200]}")
    except Exception as e:
        print(f"    [!] Direct request video completion failed: {e}")

def automate_quiz_component(driver):
    print("    [?] Executing background runtime recursive logic solver for targeted matrix block items...")
    quiz_js_script = """
    var callback = arguments[arguments.length - 1];
    (async function autoSolveQuizOptimized() {
        const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
        const getProblemId = () => {
            const problemDiv = document.querySelector('.problems-wrapper');
            if (!problemDiv) return null;
            return problemDiv.getAttribute('data-problem-id').split('type@problem+block@')[1];
        };
        const problemBlockId = getProblemId();
        if (!problemBlockId) { callback('No target operational wrapper ID extracted.'); return; }
        const isQuestionCorrect = (q) => {
            const span = document.querySelector(`#status_${problemBlockId}_${q + 1}_1`);
            return span && span.classList.contains('correct');
        };
        const selectAnswer = (q, choice) => {
            const radio = document.getElementById(`input_${problemBlockId}_${q + 1}_1_choice_${choice}`);
            if (radio && !radio.checked) {
                radio.click(); radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };
        const submitQuiz = async () => {
            const btn = document.querySelector('.submit.btn-brand');
            if (btn) { btn.click(); await wait(800); }
        };
        const totalQuestions = document.querySelectorAll('[id^="input_"][id$="_1_choice_0"]').length;
        if (totalQuestions === 0) { callback('Zero input matching options found.'); return; }
        const correctAnswers = {};
        for (let option = 0; option <= 4; option++) {
            for (let q = 1; q <= totalQuestions; q++) {
                selectAnswer(q, correctAnswers[q] !== undefined ? correctAnswers[q] : option);
                await wait(150);
            }
            await submitQuiz();
            for (let q = 1; q <= totalQuestions; q++) {
                if (correctAnswers[q] === undefined && isQuestionCorrect(q)) correctAnswers[q] = option;
            }
            if (Object.keys(correctAnswers).length === totalQuestions) break;
        }
        callback('Matrix items resolved.');
    })();
    """
    try:
        status = driver.execute_async_script(quiz_js_script)
        print(f"    [?] Quiz engine feedback: {status}")
    except Exception as e:
        print(f"    [!] Quiz engine script runtime failure: {e}")

def process_single_course(course_id):
    print(f"[>>>] SPAWNING DRIVER CONTEXT THREAD FOR COURSE ID: {course_id}")
    course_url = f"https://lms.bpkpenaburdigilearn.or.id/courses/{course_id}/course/"
    driver = setup_driver()
    try:
        print(f"[{course_id}] Injecting authentication token states...")
        inject_session_cookies(driver, course_url)
        # Create a requests session for direct POSTs (video tracking / completion)
        session = requests.Session()
        session.cookies.set("sessionid", SESSION_ID, domain="bpkpenaburdigilearn.or.id")
        session.cookies.set("csrftoken", CSRFTOKEN, domain="bpkpenaburdigilearn.or.id")
        session.cookies.set("next-auth.session-token", NEXT_AUTH_SESSION_TOKEN, domain="cms.bpkpenaburdigilearn.or.id")
        subsection_urls = collect_subsection_urls(driver, course_url)

        total_failed = 0
        for index, sub_url in enumerate(subsection_urls, start=1):
            print(f"[{course_id}] Navigating to sequence unit {index}/{len(subsection_urls)} -> {sub_url}")
            driver.get(sub_url)

            try:
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "nav.sequence-nav, .sequence-nav"))
                )
            except TimeoutException:
                print(f"[{course_id}] [!] Timeout waiting for container layout selectors. Skipping item.")
                total_failed += 1
                continue

            tab_selector = "nav.sequence-nav ol li button, .sequence-nav button, button[id^='tab_']"

            tabs = [
                tab for tab in driver.find_elements(By.CSS_SELECTOR, tab_selector)
                if tab.get_attribute("data-page-title")
            ]

            for t_idx, target_tab in enumerate(tabs):
                try:
                    tab_title = target_tab.get_attribute("data-page-title")
                except Exception:
                    # element went stale (page re-rendered) — re-fetch this one
                    tabs = [
                        tab for tab in driver.find_elements(By.CSS_SELECTOR, tab_selector)
                        if tab.get_attribute("data-page-title")
                    ]
                    if t_idx >= len(tabs):
                        total_failed += 1
                        continue
                    target_tab = tabs[t_idx]
                    tab_title = target_tab.get_attribute("data-page-title")

                check_circles = target_tab.find_elements(By.CSS_SELECTOR, ".check-circle")
                is_completed = False
                if check_circles:
                    classes = check_circles[0].get_attribute("class")
                    is_completed = "is-hidden" not in classes

                if is_completed:
                    print(f"  [-] Tab [{tab_title}] already flagged complete. Skipping.")
                    continue

                print(f"  [>] Processing unit item tab: [{tab_title}]")
                try:
                    driver.execute_script("arguments[0].click();", target_tab)
                    WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located((
                            By.CSS_SELECTOR,
                            '[data-block-type], .problems-wrapper'
                        ))
                    )
                except Exception as click_err:
                    print(f"  [!] Element focus click intercept failure: {click_err}")
                    total_failed += 1       # <-- count it
                    continue

                is_video = driver.find_elements(By.CSS_SELECTOR, '[data-block-type="bunnynet"], iframe#bunnynet')
                is_quiz = driver.find_elements(By.CSS_SELECTOR, '.problems-wrapper')

                if is_video:
                    automate_video_component(session, driver)
                    time.sleep(1)

                if is_quiz:
                    input_count = len(driver.find_elements(
                        By.CSS_SELECTOR,
                        '.problems-wrapper input[type="text"]:not([type="hidden"]), '
                        '.problems-wrapper textarea, '
                        '.problems-wrapper [contenteditable="true"]'
                    ))
                    if input_count:
                        save_input_required_link(
                            course_id,
                            driver.current_url,
                            tab_title,
                            input_count,
                        )
                    automate_quiz_component(driver)

                if not is_video and not is_quiz:
                    print("    [*] Executing standard completion handshake for static page entity components...")
                    driver.execute_script("""
                        const b = document.querySelector('[data-block-type="html"]');
                        if (!b) return;
                        fetch(`/courses/${b.dataset.courseId}/xblock/${b.dataset.usageId}/handler/publish_completion`, {
                            method: "POST", credentials: "include",
                            headers: { "Content-Type": "application/json", "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] },
                            body: JSON.stringify({ completion: 1 })
                        });
                    """)
                    time.sleep(1.5)

        if total_failed == 0:
            print(f"[VVV] CLOSING CONTEXT SUCCESS WORKFLOW THREAD FOR COURSE ID: {course_id}")
            save_completed_course(course_id)
        else:
            print(f"[!!!] {course_id}: {total_failed} failure(s) — NOT marking complete, will retry next run")
        
    except Exception as general_err:
        print(f"[!!!] Worker exception encountered on Course thread {course_id}: {general_err}")
    finally:
        driver.quit()

def main():
    print("[*] INITIALIZING AUTOMATION PIPELINE SEQUENCE ENGINE...")
    all_course_ids = fetch_and_enroll_all_courses()
    
    # Load completed history and filter the list
    completed_ids = load_completed_courses()
    pending_course_ids = [cid for cid in all_course_ids if cid not in completed_ids]
    
    print(f"\n[+] PIPELINE LOAD COMPLETE. Total parsed execution target list: {len(all_course_ids)} elements.")
    print(f"[+] Already completed (Skipping): {len(completed_ids)} items.")
    print(f"[+] Active work target list: {len(pending_course_ids)} elements.")
    print(f"[+] CONCURRENCY THRESHOLD LOCKED AT: {MAX_CONCURRENT_COURSES} parallel processes.\n")
    
    if not pending_course_ids:
        print("[*] All courses are completed! Nothing left to process.")
        return
        
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_COURSES) as executor:
        executor.map(process_single_course, pending_course_ids)
        
    print("\n[*] PIPELINE EXECUTION SUMMARY COMPLETE. ALL ALLOCATED THREAD STORAGE INSTANCES CLOSED.")

if __name__ == "__main__":
    main()