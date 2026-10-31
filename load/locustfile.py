import os
import re
import random
from io import BytesIO

from locust import HttpUser, task, between
from locust import runners
from gevent import sleep as gevent_sleep

if os.environ.get("LOCUST_DISABLE_CPU_MONITOR") == "1":
    def _noop_monitor(self):
        while True:
            gevent_sleep(3600)
    runners.Runner.monitor_cpu_and_memory = _noop_monitor

PROFILE = os.environ.get("LOCUST_PROFILE", "mixed").lower()


def _extract_csrf(html: str) -> str | None:
    m = re.search(r'name=\"csrf_token\" value=\"([^\"]+)\"', html)
    return m.group(1) if m else None


def _extract_first_job_id(html: str) -> str | None:
    m = re.search(r'href=\"/jobs/(\\d+)\"', html)
    if m:
        return m.group(1)
    fallback = os.environ.get("LOCUST_JOB_ID")
    if fallback == "random":
        try:
            max_id = int(os.environ.get("LOCUST_JOB_MAX", "0"))
        except ValueError:
            max_id = 0
        if max_id > 0:
            return str(random.randint(1, max_id))
    if PROFILE == "workflow":
        return fallback or "1"
    return fallback


def _extract_template_id(html: str) -> str | None:
    m = re.search(r'<option value=\"(\\d+)\">', html)
    return m.group(1) if m else None


def _extract_select_option(name: str, html: str) -> str | None:
    pattern = rf'<select[^>]*name=\"{re.escape(name)}\"[^>]*>(.*?)</select>'
    m = re.search(pattern, html, re.S)
    if not m:
        return None
    select_html = m.group(1)
    for opt in re.findall(r'<option value=\"([^\"]*)\">', select_html):
        if opt:
            return opt
    return None


def _extract_assigned_tech_id(html: str) -> str | None:
    pattern = r'<option value=\"([^\"]+)\">(.*?)</option>'
    for value, label in re.findall(pattern, html, re.S):
        if not value:
            continue
        if "technician@example.com" in label:
            return value
    return None


def _extract_hidden(name: str, html: str) -> str | None:
    m = re.search(rf'name=\"{re.escape(name)}\" value=\"([^\"]+)\"', html)
    return m.group(1) if m else None


def _extract_visible_ids(html: str) -> list[str]:
    raw = _extract_hidden("visible_ids", html) or ""
    return [v.strip() for v in raw.split(",") if v.strip().isdigit()]


class BaseUser(HttpUser):
    abstract = True
    wait_time = between(1, 3)
    csrf_token = None

    def on_start(self):
        self.login()

    def login(self):
        resp = self.client.get("/login")
        token = _extract_csrf(resp.text)
        self.csrf_token = token
        payload = {
            "username": self.username,
            "password": self.password,
        }
        if token:
            payload["csrf_token"] = token
        self.client.post(
            "/login",
            data=payload,
            headers={"Referer": self.client.base_url + "/login"},
        )


class OfficeUser(BaseUser):
    weight = 3
    username = os.environ.get("OFFICE_USER", "office@example.com")
    password = os.environ.get("OFFICE_PASS", "Password123!")

    def _create_job(self):
        resp = self.client.get("/jobs/create")
        token = _extract_csrf(resp.text)
        template_id = _extract_template_id(resp.text)
        assigned_to_id = _extract_assigned_tech_id(resp.text) or _extract_select_option("assigned_to_id", resp.text)
        if not token or not template_id:
            return
        job_num = f"LOAD-{random.randint(1000, 9999)}"
        self.client.post(
            "/jobs/create",
            data={
                "csrf_token": token,
                "job_number": job_num,
                "customer_name": "LoadTest",
                "engine_type": "LoadEngine",
                "serial_number": "",
                "template_id": template_id,
                "assigned_to_id": assigned_to_id or "",
            },
            headers={"Referer": self.client.base_url + "/jobs/create"},
        )

    @task(3)
    def create_job_mixed(self):
        if PROFILE == "workflow":
            return
        self._create_job()

    @task(6)
    def create_job_workflow(self):
        if PROFILE != "workflow":
            return
        self._create_job()

    @task(2)
    def parts_list(self):
        if PROFILE == "workflow":
            return
        resp = self.client.get("/jobs")
        job_id = _extract_first_job_id(resp.text)
        if job_id:
            self.client.get(f"/jobs/{job_id}/parts")
            self.client.get(f"/jobs/{job_id}")


class TechUser(BaseUser):
    weight = 3
    username = os.environ.get("TECH_USER", "technician@example.com")
    password = os.environ.get("TECH_PASS", "Password123!")

    @task(2)
    def open_survey(self):
        if PROFILE == "workflow":
            return
        resp = self.client.get("/jobs")
        job_id = _extract_first_job_id(resp.text)
        if job_id:
            self.client.get(f"/jobs/{job_id}/survey")

    @task(2)
    def save_survey(self):
        if PROFILE == "workflow":
            return
        resp = self.client.get("/jobs")
        job_id = _extract_first_job_id(resp.text)
        if not job_id:
            return
        page = self.client.get(f"/jobs/{job_id}/survey")
        token = _extract_csrf(page.text)
        survey_version = _extract_hidden("survey_version", page.text) or "0"
        visible_ids = _extract_hidden("visible_ids", page.text) or ""
        payload = {
            "action": "save",
            "survey_version": survey_version,
            "visible_ids": visible_ids,
        }
        if token:
            payload["csrf_token"] = token
        self.client.post(
            f"/jobs/{job_id}/survey",
            data=payload,
            headers={"Referer": self.client.base_url + f"/jobs/{job_id}/survey"},
        )

    def _complete_survey(self):
        resp = self.client.get("/jobs")
        job_id = _extract_first_job_id(resp.text)
        if not job_id:
            return
        pre = self.client.get(f"/jobs/{job_id}/pre_survey")
        token = _extract_csrf(pre.text)
        data = {"notes": ""}
        if token:
            data["csrf_token"] = token
        self.client.post(
            f"/jobs/{job_id}/pre_survey",
            data=data,
            headers={"Referer": self.client.base_url + f"/jobs/{job_id}/pre_survey"},
        )
        page = self.client.get(f"/jobs/{job_id}/survey")
        if "needs_seed" in page.text:
            self.client.post(f"/jobs/{job_id}/survey/seed")
            page = self.client.get(f"/jobs/{job_id}/survey")
        token = _extract_csrf(page.text)
        survey_version = _extract_hidden("survey_version", page.text) or "0"
        ids = _extract_visible_ids(page.text)
        if not ids:
            return
        payload = {
            "action": "complete",
            "survey_version": survey_version,
            "visible_ids": ",".join(ids),
        }
        for item_id in ids:
            payload[f"decision_{item_id}"] = "reuse"
            payload[f"measurement_value_{item_id}"] = "15"
            payload[f"spec_min_{item_id}"] = "10"
            payload[f"spec_max_{item_id}"] = "20"
            payload[f"measurement_unit_{item_id}"] = "mm"
        if token:
            payload["csrf_token"] = token
        self.client.post(
            f"/jobs/{job_id}/survey",
            data=payload,
            headers={"Referer": self.client.base_url + f"/jobs/{job_id}/survey"},
        )

    @task(1)
    def complete_survey_mixed(self):
        if PROFILE == "workflow":
            return
        self._complete_survey()

    @task(6)
    def complete_survey_workflow(self):
        if PROFILE != "workflow":
            return
        self._complete_survey()


class StoresUser(BaseUser):
    weight = 2
    username = os.environ.get("STORES_USER", "stores@example.com")
    password = os.environ.get("STORES_PASS", "Password123!")

    @task(3)
    def stores_hub(self):
        self.client.get("/stores?view=master")


class AdminUser(BaseUser):
    weight = 1
    username = os.environ.get("ADMIN_USER", "admin@example.com")
    password = os.environ.get("ADMIN_PASS", "Password123!")

    def _upload_attachment(self):
        resp = self.client.get("/jobs")
        job_id = _extract_first_job_id(resp.text)
        if not job_id:
            return
        page = self.client.get(f"/jobs/{job_id}/attachments")
        token = _extract_csrf(page.text)
        size_mb = int(os.environ.get("ATTACHMENT_SIZE_MB", "1"))
        payload = BytesIO(b"x" * size_mb * 1024 * 1024)
        data = {}
        if token:
            data["csrf_token"] = token
        self.client.post(
            f"/jobs/{job_id}/attachments",
            files={"file": ("load.txt", payload, "text/plain")},
            data=data,
            headers={"Referer": self.client.base_url + f"/jobs/{job_id}/attachments"},
        )

    @task(1)
    def upload_attachment_mixed(self):
        if PROFILE == "workflow":
            return
        self._upload_attachment()

    @task(4)
    def upload_attachment_workflow(self):
        if PROFILE != "workflow":
            return
        self._upload_attachment()
