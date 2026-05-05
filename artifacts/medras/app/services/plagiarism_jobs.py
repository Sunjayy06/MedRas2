"""Background job manager for the plagiarism rewrite pipeline.

Replaces the long-lived streaming connection with a polling/job model
that scales to 200-page documents:

* Each section is processed sequentially in a daemon worker thread.
* Per-section progress is queryable by ``job_id`` over plain HTTP, so
  proxies, mobile sleep, or flaky networks can never stall the pipeline.
* Per-section hard timeout (``SECTION_TIMEOUT_SECONDS``) ensures one
  slow stage cannot block the rest of the document.
* At most ``MAX_CONCURRENT_JOBS`` run at once and ``MAX_TOTAL_BYTES`` of
  text data is held in memory across all jobs combined.
* Completed/failed/cancelled jobs are evicted ``JOB_TTL_SECONDS`` after
  they finish — cleanup runs lazily on every ``create_job``/``get_job``
  call so we don't need a background scheduler thread.
* The original section text is dropped from the in-memory job state as
  soon as the section finishes successfully (per product spec). For
  failed/timed-out sections we keep the original so the user can retry
  just those sections without re-uploading the document.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.services import plagiarism_analyzer as pa

log = get_logger(__name__)

# ---- tunables (kept in one place so tests can monkey-patch them) ----
MAX_CONCURRENT_JOBS = 3
MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB across ALL jobs in memory
JOB_TTL_SECONDS = 30 * 60            # remove finished jobs after 30 min
SECTION_TIMEOUT_SECONDS = 60.0       # per-stage hard wall-clock cap
# Circuit breaker: if this many sections in a row time out we abort the
# rest of the job. Continuing would just waste compute (and possibly
# tokens) while the user waits — far better to fail fast and let them
# retry once the provider stabilises.
CONSECUTIVE_TIMEOUT_LIMIT = 2


def _section_bytes(section: Dict[str, Any]) -> int:
    """Sum of all retained text strings on a section.

    Used by the worker to keep ``JobState.bytes_tracked`` honest after
    each transition (admit-time estimate vs. actually retained data).
    """
    total = 0
    for key in (
        "original", "final_text",
        "stage_a_text", "stage_b_text", "stage_c_text",
        "error",
    ):
        v = section.get(key)
        if v:
            total += len(str(v).encode("utf-8"))
    return total


class CapacityError(RuntimeError):
    """Raised when a new job would exceed concurrency or memory caps.

    The route translates this into HTTP 429 with the user-facing message
    so the browser shows: *"The system is currently processing other
    documents. Please try again in a few minutes."*
    """


@dataclass
class JobState:
    """In-memory state for one plagiarism rewrite job.

    All mutating access must happen while holding ``JobManager._lock``.
    Sections are stored in input order; each entry starts as
    ``{"status": "pending", "label": ..., "original": ...}`` and is
    rewritten in place by the worker thread.
    """

    job_id: str
    status: str  # queued | processing | complete | failed | cancelled
    title: str
    filename: Optional[str]
    protected_terms: List[str]
    sections: List[Dict[str, Any]]
    started_at: float
    updated_at: float
    completed_at: Optional[float] = None
    completion_times: List[float] = field(default_factory=list)
    current_index: Optional[int] = None
    current_pass_num: int = 0
    current_pass_label: str = ""
    bytes_tracked: int = 0
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class JobManager:
    """Process-wide singleton coordinating background plagiarism jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, JobState] = {}
        self._lock = threading.Lock()

    # ---- internal helpers (caller MUST hold self._lock) ----
    def _cleanup_stale_locked(self) -> None:
        now = time.time()
        stale = [
            jid for jid, j in self._jobs.items()
            if j.status in ("complete", "failed", "cancelled")
            and j.completed_at is not None
            and (now - j.completed_at) > JOB_TTL_SECONDS
        ]
        for jid in stale:
            log.info("plagiarism_jobs: evicting stale job %s", jid)
            del self._jobs[jid]

    def _active_count_locked(self) -> int:
        return sum(
            1 for j in self._jobs.values()
            if j.status in ("queued", "processing")
        )

    def _total_bytes_locked(self) -> int:
        return sum(j.bytes_tracked for j in self._jobs.values())

    # ---- public API ----
    def create_job(
        self,
        sections: List[Dict[str, str]],
        protected_terms: Optional[List[str]],
        title: str,
        filename: Optional[str],
        report: Optional[Dict[str, Any]] = None,
    ) -> JobState:
        """Register a new job and spawn its background worker.

        Raises ``CapacityError`` if the system has hit
        ``MAX_CONCURRENT_JOBS`` or would exceed ``MAX_TOTAL_BYTES``.
        Always evicts stale finished jobs first so a user who retried
        twenty minutes ago doesn't permanently steal a slot.
        """
        if not sections:
            raise ValueError("create_job requires at least one section")

        with self._lock:
            self._cleanup_stale_locked()

            # Estimate memory footprint: original + ~3 stage outputs +
            # final text. Real footprint is usually less because empty
            # / references-only sections are not rewritten, but we err
            # on the side of admitting fewer concurrent giant jobs than
            # too many.
            input_bytes = sum(
                len((s.get("text") or "").encode("utf-8")) for s in sections
            )
            estimated_with_results = input_bytes * 5

            if (
                self._total_bytes_locked() + estimated_with_results
                > MAX_TOTAL_BYTES
            ):
                raise CapacityError(
                    "The system is currently processing other documents "
                    "and is at memory capacity. Please try again in a "
                    "few minutes."
                )

            if self._active_count_locked() >= MAX_CONCURRENT_JOBS:
                raise CapacityError(
                    "The system is currently processing other documents. "
                    "Please try again in a few minutes."
                )

            job_id = uuid.uuid4().hex[:12]
            now = time.time()
            # Resolve per-section intensity from the plagiarism report
            # (Path A). Falls back to "normal" for every section when no
            # report was supplied (Path B). Imported lazily to avoid a
            # circular dependency at module load.
            from app.services import report_parser as rp
            flagged_map = (report or {}).get("flagged_map") or {}
            section_states: List[Dict[str, Any]] = []
            for i, sec in enumerate(sections):
                label = (sec.get("label") or "").strip() or f"Section {i+1}"
                intensity, sim_pct = rp.match_intensity_for_label(label, flagged_map)
                section_states.append({
                    "index": i,
                    "label": label,
                    "original": sec.get("text") or "",
                    "status": "pending",
                    "final_text": "",
                    "stage_a_text": "",
                    "stage_b_text": "",
                    "stage_c_text": "",
                    "stage_models": {},
                    "edits": 0,
                    "missing_terms": [],
                    "fallback_used": False,
                    "skipped": False,
                    "skip_reason": None,
                    "elapsed_seconds": 0.0,
                    "error": None,
                    "quality": None,
                    "intensity": intensity,
                    "similarity_percent": sim_pct,
                })

            state = JobState(
                job_id=job_id,
                status="queued",
                title=title,
                filename=filename,
                protected_terms=list(protected_terms or []),
                sections=section_states,
                started_at=now,
                updated_at=now,
                bytes_tracked=estimated_with_results,
            )
            # Stash the plagiarism-report metadata on the state object
            # so serialize_job can echo it back to the UI for the Path A
            # summary box ("Based on your Turnitin report: …").
            state.report_meta = {
                "software": (report or {}).get("software"),
                "flagged_map": flagged_map,
                "summary": rp.summarise_report(flagged_map) if flagged_map else None,
            } if report else None
            self._jobs[job_id] = state

        # Spawn worker OUTSIDE the lock so a slow start doesn't block
        # other create/get calls.
        threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"pm-job-{job_id}",
        ).start()
        return state

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            self._cleanup_stale_locked()
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return False
            if j.status in ("complete", "failed", "cancelled"):
                # Already terminal — drop it now so memory is released.
                self._jobs.pop(job_id, None)
                return True
            j.cancel_event.set()
            return True

    def retry_failed(self, job_id: str) -> Optional[JobState]:
        """Re-queue only the failed/timed-out sections of a finished job.

        Successful sections are kept as-is; their original text was
        already freed when they completed, so we don't need to touch
        them. Raises ``RuntimeError`` if the job is still running.
        """
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return None
            if j.status in ("queued", "processing"):
                raise RuntimeError("Job is still running; wait for it to finish")

            failed = [
                s for s in j.sections
                if s["status"] in ("failed", "timed_out")
            ]
            if not failed:
                return j

            for s in failed:
                # Reset to pending so the worker re-processes it. We kept
                # the original text on failed sections precisely so this
                # is possible without re-uploading.
                if not (s.get("original") or "").strip():
                    # Defensive: shouldn't happen, but if original was
                    # somehow lost, mark it permanently failed instead
                    # of silently ignoring.
                    s["status"] = "failed"
                    s["error"] = (
                        "Cannot retry: original text is no longer in "
                        "memory. Please re-upload the document."
                    )
                    continue
                s["status"] = "pending"
                s["error"] = None
                s["final_text"] = ""
                s["stage_a_text"] = ""
                s["stage_b_text"] = ""
                s["stage_c_text"] = ""

            # Recompute bytes tracked (failed sections still hold their
            # originals; successful ones are already freed).
            j.bytes_tracked = sum(
                len((s.get("original") or "").encode("utf-8"))
                + len((s.get("final_text") or "").encode("utf-8"))
                for s in j.sections
            )
            j.status = "queued"
            j.updated_at = time.time()
            j.completed_at = None
            j.cancel_event = threading.Event()

        threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"pm-job-{job_id}-retry",
        ).start()
        return j

    # ---- worker ----
    def _run_job(self, job_id: str) -> None:
        """Daemon worker — run pending sections one at a time."""
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.status = "processing"
            j.updated_at = time.time()

        consecutive_timeouts = 0
        try:
            # Snapshot pending indices up front so concurrent reads of
            # j.sections don't surprise us mid-loop.
            with self._lock:
                pending_indices = [
                    s["index"] for s in j.sections if s["status"] == "pending"
                ]

            for idx in pending_indices:
                if j.cancel_event.is_set():
                    break

                with self._lock:
                    s = j.sections[idx]
                    if s["status"] != "pending":
                        continue
                    label = s["label"]
                    body = s.get("original") or ""
                    j.current_index = idx
                    j.current_pass_num = 0
                    j.current_pass_label = "Preparing…"
                    s["status"] = "processing"
                    j.updated_at = time.time()

                def _on_pass(num: int, label_text: str, _j=j) -> None:
                    with self._lock:
                        _j.current_pass_num = num
                        _j.current_pass_label = label_text
                        _j.updated_at = time.time()

                started = time.time()
                try:
                    result = pa.process_one_section(
                        index=idx,
                        label=label,
                        text=body,
                        protected_terms=j.protected_terms,
                        stage_timeout=SECTION_TIMEOUT_SECONDS,
                        progress_cb=_on_pass,
                        intensity=s.get("intensity") or "normal",
                    )
                except pa.ProviderQuotaExhausted as exc:
                    # Both providers exhausted — abort the whole job;
                    # subsequent sections will hit the same wall.
                    log.warning(
                        "plagiarism_jobs: job %s aborted, providers exhausted: %s",
                        job_id, pa.sanitize_error_message(exc),
                    )
                    with self._lock:
                        s["status"] = "failed"
                        s["error"] = (
                            "Both AI providers are out of quota right now. "
                            "Please try again later."
                        )
                        # Mark the rest as failed-because-aborted so the
                        # UI can show a single coherent banner.
                        for other in j.sections:
                            if other["status"] in ("pending", "processing"):
                                other["status"] = "failed"
                                other["error"] = (
                                    "Skipped because both AI providers ran "
                                    "out of quota mid-job."
                                )
                        j.status = "failed"
                        j.error = "providers_exhausted"
                        j.completed_at = time.time()
                        j.updated_at = j.completed_at
                        j.current_index = None
                        j.current_pass_label = ""
                    return
                except Exception as exc:  # noqa: BLE001
                    log.exception(
                        "plagiarism_jobs: unexpected crash in job %s section %s",
                        job_id, idx,
                    )
                    with self._lock:
                        s["status"] = "failed"
                        s["error"] = pa.sanitize_error_message(exc)
                    continue

                # Success path: merge result, update bookkeeping, free
                # the original text if appropriate.
                elapsed = time.time() - started
                status = result.get("status")
                with self._lock:
                    # Preserve similarity_percent — the rewriter never
                    # sets it but the UI needs it for the "Was X% similar"
                    # badge on every card.
                    sim_pct = s.get("similarity_percent")
                    s.update(result)
                    if sim_pct is not None and s.get("similarity_percent") is None:
                        s["similarity_percent"] = sim_pct
                    if status == "complete" and not result.get("skipped"):
                        j.completion_times.append(elapsed)
                    # Drop original text from memory for any section
                    # that won't be retried (complete or skipped). We
                    # retain it for failed/timed_out so retry works
                    # without a re-upload. Stage A/B intermediates are
                    # also cleared on completion — only the final text
                    # is needed for the download. Keep stage_c_text
                    # because it equals final_text and the UI may show
                    # the staged view.
                    if status in ("complete", "skipped"):
                        s["original"] = ""
                        s["stage_a_text"] = ""
                        s["stage_b_text"] = ""
                    # Recompute bytes_tracked from what's actually
                    # retained across ALL sections rather than
                    # incrementally adjusting (which drifted because
                    # the admit-time estimate didn't match the real
                    # set of strings we end up holding).
                    j.bytes_tracked = sum(_section_bytes(sec) for sec in j.sections)
                    j.updated_at = time.time()

                # Circuit breaker — if we've timed out N times in a
                # row, abort the rest of the job. Subsequent sections
                # would almost certainly fail the same way and just
                # waste tokens.
                if status == "timed_out":
                    consecutive_timeouts += 1
                else:
                    consecutive_timeouts = 0
                if consecutive_timeouts >= CONSECUTIVE_TIMEOUT_LIMIT:
                    log.warning(
                        "plagiarism_jobs: job %s aborting after %d consecutive timeouts",
                        job_id, consecutive_timeouts,
                    )
                    with self._lock:
                        for other in j.sections:
                            if other["status"] in ("pending", "processing"):
                                other["status"] = "failed"
                                other["error"] = (
                                    "Skipped: the provider was timing out repeatedly. "
                                    "Use Retry once the provider stabilises."
                                )
                        j.error = "consecutive_timeouts"
                    break

            with self._lock:
                if j.cancel_event.is_set():
                    j.status = "cancelled"
                else:
                    j.status = "complete"
                j.completed_at = time.time()
                j.updated_at = j.completed_at
                j.current_index = None
                j.current_pass_label = ""
                j.current_pass_num = 0
        except Exception as exc:  # noqa: BLE001
            log.exception("plagiarism_jobs: worker thread crashed for %s", job_id)
            with self._lock:
                j.status = "failed"
                j.error = pa.sanitize_error_message(exc)
                j.completed_at = time.time()
                j.updated_at = j.completed_at


def _safe_error(value: Any) -> Optional[str]:
    """Defensive sanitization for ANY error string we expose.

    Even though every assignment we know of already passes through
    ``pa.sanitize_error_message``, we strip again at the serialization
    boundary so a future contributor can't accidentally leak provider
    keys / bearer tokens by setting ``j.error = str(exc)`` directly.
    """
    if value is None:
        return None
    return pa.sanitize_error_message(value)


def serialize_job(j: JobState) -> Dict[str, Any]:
    """Build the JSON payload returned by GET /jobs/{job_id}.

    Strips ``original`` text from sections that are still pending or
    processing (the client doesn't need it and it can be huge), but
    keeps it on failed/timed_out sections so the retry flow has it.
    Successful sections have already had their original cleared from
    in-memory state by the worker.
    """
    completed = sum(
        1 for s in j.sections if s["status"] in ("complete", "skipped")
    )
    failed = sum(
        1 for s in j.sections if s["status"] in ("failed", "timed_out")
    )
    total = len(j.sections)
    settled = completed + failed
    pct = round(100 * settled / total) if total else 0

    end_ts = j.completed_at or time.time()
    elapsed = max(0.0, end_ts - j.started_at)

    eta: Optional[float] = None
    if j.status == "processing" and j.completion_times:
        avg = sum(j.completion_times) / len(j.completion_times)
        remaining = max(0, total - settled)
        eta = round(avg * remaining)

    out_sections: List[Dict[str, Any]] = []
    for s in j.sections:
        # Drop original from in-flight / pending entries to keep the
        # poll response small. The browser already has the original
        # text in its own state from the upload.
        copy = dict(s)
        if copy["status"] in ("pending", "processing"):
            copy.pop("original", None)
        # Defensive sanitization — never let raw provider errors out.
        if copy.get("error"):
            copy["error"] = _safe_error(copy["error"])
        out_sections.append(copy)

    current_label = None
    if j.current_index is not None and 0 <= j.current_index < total:
        current_label = j.sections[j.current_index]["label"]

    return {
        "job_id": j.job_id,
        "status": j.status,
        "title": j.title,
        "filename": j.filename,
        "protected_terms": j.protected_terms,
        "total_sections": total,
        "completed_count": completed,
        "failed_count": failed,
        "current_index": j.current_index,
        "current_section": current_label,
        "current_pass_num": j.current_pass_num,
        "current_pass_label": j.current_pass_label,
        "total_passes": 3,
        "percent": pct,
        "started_at": j.started_at,
        "completed_at": j.completed_at,
        "elapsed_seconds": round(elapsed, 1),
        "eta_seconds": eta,
        "error": _safe_error(j.error),
        "sections": out_sections,
        "report_meta": getattr(j, "report_meta", None),
    }


# Process-wide singleton imported by the route module.
job_manager = JobManager()
