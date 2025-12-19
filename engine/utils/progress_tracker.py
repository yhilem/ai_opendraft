"""
Progress tracking utility for draft generation.
Updates database with real-time progress information.
Includes activity logging for rich UI feedback.

Production Notes:
- Uses logging module instead of print() to avoid "Broken pipe" errors
- Exceptions in progress updates are logged but don't crash generation
- Activity log is persisted to database for UI feedback
"""
import os
import sys
import time
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

# Configure module logger
logger = logging.getLogger(__name__)


# Activity message templates for different stages
ACTIVITY_MESSAGES = {
    # Research phase
    "starting_research": "Starting academic research...",
    "querying_crossref": "Querying CrossRef for peer-reviewed papers...",
    "querying_semantic_scholar": "Searching Semantic Scholar...",
    "querying_gemini": "Using AI-powered search...",
    "scout_completed": "Found {sources_count} academic sources",
    "research_complete": "Research phase complete",

    # Structure phase
    "creating_outline": "Designing thesis structure...",
    "outline_complete": "Thesis outline ready",
    "processing_citations": "Processing {sources_count} citations...",

    # Writing phase
    "starting_composition": "Beginning chapter composition...",
    "writing_introduction": "Writing Introduction...",
    "introduction_complete": "Introduction complete",
    "writing_literature_review": "Writing Literature Review...",
    "literature_review_complete": "Literature Review complete",
    "writing_methodology": "Writing Methodology...",
    "methodology_complete": "Methodology complete",
    "writing_results": "Writing Analysis & Results...",
    "results_complete": "Analysis & Results complete",
    "writing_discussion": "Writing Discussion...",
    "discussion_complete": "Discussion complete",
    "writing_conclusion": "Writing Conclusion...",
    "conclusion_complete": "Conclusion complete",
    "writing_appendices": "Writing Appendices...",
    "appendices_complete": "Appendices complete",

    # Compile phase
    "assembling_draft": "Assembling final thesis...",
    "compiling_citations": "Compiling bibliography...",
    "generating_abstract": "Generating abstract...",
    "compilation_complete": "Compilation complete",

    # Export phase
    "exporting_pdf": "Generating PDF...",
    "pdf_complete": "PDF generated",
    "exporting_docx": "Generating Word document...",
    "docx_complete": "Word document generated",
    "creating_zip": "Creating download package...",
    "export_complete": "Export complete",
}

# Event type mapping
EVENT_TYPE_KEYWORDS = {
    "search": ["querying", "searching", "starting_research"],
    "found": ["found", "complete", "ready", "generated"],
    "writing": ["writing", "composition", "assembling"],
    "milestone": ["_complete", "outline_ready"],
    "error": ["error", "failed"],
}

# Phase emoji mapping
PHASE_EMOJIS = {
    "research": "🔍",
    "structure": "📋",
    "writing": "✍️",
    "compiling": "🔧",
    "exporting": "📄",
    "completed": "✅",
    "error": "❌",
}


class ProgressTracker:
    """Tracks and updates draft generation progress in real-time with activity logging."""

    MAX_ACTIVITY_LOG_SIZE = 50  # Keep last N entries

    def __init__(self, draft_id: str = None, user_id: str = None, table_name: str = "theses", supabase_client=None, cancellation_checker=None):
        """
        Initialize progress tracker.

        Args:
            draft_id: Draft ID to track progress for
            user_id: User ID to track progress for (legacy support)
            table_name: Table name to update. Default: 'theses'
            supabase_client: Supabase client instance (optional, will create if not provided)
            cancellation_checker: CancellationChecker instance for checking cancellation requests
        """
        self.draft_id = draft_id
        self.user_id = user_id or draft_id  # Fallback to draft_id if user_id not provided
        self.table_name = table_name
        self.record_id = draft_id if draft_id else user_id  # ID to use for queries
        self._activity_log: List[Dict[str, Any]] = []  # Local cache of activity log
        self.cancellation_checker = cancellation_checker

        if supabase_client:
            self.supabase = supabase_client
        else:
            from supabase import create_client
            supabase_url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
            supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            self.supabase = create_client(supabase_url, supabase_key)

    def check_cancellation(self):
        """Check for cancellation and raise if cancelled."""
        if self.cancellation_checker:
            self.cancellation_checker.raise_if_cancelled()

    def send_heartbeat(self):
        """Send heartbeat to indicate worker is alive. Call during long operations.
        Note: Heartbeat via last_heartbeat_at column is disabled - column doesn't exist in DB yet.
        """
        if self.cancellation_checker:
            # This also sends heartbeat
            self.cancellation_checker.check_and_heartbeat()
        # Note: Direct heartbeat update disabled - last_heartbeat_at column doesn't exist
        # When the column is added to DB, uncomment this:
        # else:
        #     try:
        #         self.supabase.table(self.table_name).update({
        #             'last_heartbeat_at': datetime.now().isoformat()
        #         }).eq('id', self.record_id).execute()
        #     except Exception as e:
        #         print(f"Heartbeat failed: {e}")

    def _get_event_type(self, stage: str) -> str:
        """Determine event type from stage name."""
        stage_lower = stage.lower() if stage else ""

        for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
            if any(kw in stage_lower for kw in keywords):
                return event_type
        return "info"

    def _format_activity_message(self, stage: str, details: Optional[Dict] = None) -> str:
        """Format activity message for a stage."""
        if stage in ACTIVITY_MESSAGES:
            message = ACTIVITY_MESSAGES[stage]
            # Format with details if provided
            if details and "{" in message:
                try:
                    return message.format(**details)
                except KeyError:
                    return message.replace("{sources_count}", str(details.get("sources_count", "?")))
            return message

        # Fallback: convert stage name to readable text
        return stage.replace("_", " ").title() if stage else "Processing..."

    def _get_phase_emoji(self, phase: str) -> str:
        """Get emoji for a phase."""
        return PHASE_EMOJIS.get(phase, "📌")

    def _add_activity_entry(self, phase: str, stage: str, details: Optional[Dict] = None):
        """Add an entry to the activity log."""
        entry = {
            "id": f"{phase}_{stage}_{int(time.time() * 1000)}",
            "timestamp": datetime.now().isoformat(),
            "type": self._get_event_type(stage),
            "message": self._format_activity_message(stage, details),
            "icon": self._get_phase_emoji(phase),
        }

        self._activity_log.append(entry)

        # Keep only last N entries
        if len(self._activity_log) > self.MAX_ACTIVITY_LOG_SIZE:
            self._activity_log = self._activity_log[-self.MAX_ACTIVITY_LOG_SIZE:]

        return entry
    
    def update_phase(
        self,
        phase: str,
        progress_percent: int = 0,
        sources_count: Optional[int] = None,
        chapters_count: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Update the current phase and progress with activity logging.

        Args:
            phase: Phase name (research, writing, formatting, exporting, completed)
            progress_percent: Overall progress percentage (0-100)
            sources_count: Number of sources/citations found
            chapters_count: Number of chapters generated
            details: Additional details (dict) to store. Include 'stage' key for activity logging.
        """
        try:
            # Extract stage from details for activity logging
            stage = details.get("stage", phase) if details else phase

            # Add activity entry
            activity_details = details.copy() if details else {}
            if sources_count is not None:
                activity_details["sources_count"] = sources_count
            if chapters_count is not None:
                activity_details["chapters_count"] = chapters_count

            self._add_activity_entry(phase, stage, activity_details)

            # Build progress_details with activity_log
            progress_details = details.copy() if details else {}
            progress_details["activity_log"] = self._activity_log
            progress_details["stage"] = stage

            update_data = {
                "current_phase": phase,
                "progress_percent": progress_percent,
                "progress_details": progress_details,
                "updated_at": datetime.now().isoformat()
            }

            if sources_count is not None:
                update_data["sources_count"] = sources_count

            if chapters_count is not None:
                update_data["chapters_count"] = chapters_count

            self.supabase.table(self.table_name).update(update_data).eq("id", self.record_id).execute()

            logger.info(f"Progress [{self.table_name}]: {phase} ({progress_percent}%) | Sources: {sources_count or 0} | Chapters: {chapters_count or 0}")

        except Exception as e:
            # Don't fail draft generation if progress update fails
            # Log to stderr which is more resilient than stdout
            logger.warning(f"Progress update failed: {e}")

    def log_activity(self, message: str, event_type: str = "info", phase: str = None):
        """
        Log a custom activity event without changing the current phase/progress.
        Useful for logging intermediate steps like "Found: Paper X" during research.

        Args:
            message: The message to display in the activity feed
            event_type: One of 'search', 'found', 'writing', 'milestone', 'info', 'error'
            phase: Phase to use for emoji (defaults to current inferred phase)
        """
        try:
            entry = {
                "id": f"custom_{event_type}_{int(time.time() * 1000)}",
                "timestamp": datetime.now().isoformat(),
                "type": event_type,
                "message": message,
                "icon": self._get_phase_emoji(phase or "research"),
            }

            self._activity_log.append(entry)

            # Keep only last N entries
            if len(self._activity_log) > self.MAX_ACTIVITY_LOG_SIZE:
                self._activity_log = self._activity_log[-self.MAX_ACTIVITY_LOG_SIZE:]

            # Update just the activity_log in progress_details
            self.supabase.table(self.table_name).update({
                "progress_details": {"activity_log": self._activity_log},
                "updated_at": datetime.now().isoformat()
            }).eq("id", self.record_id).execute()

        except Exception as e:
            logger.warning(f"Activity log update failed: {e}")

    def log_source_found(self, title: str, authors: List[str] = None, year: int = None, source_type: str = "paper"):
        """
        Log when a research source is found - appears in activity log.
        Shows users sources as they're discovered in real-time.

        Args:
            title: Paper/source title
            authors: List of author names
            year: Publication year
            source_type: Type of source (paper, article, book, etc.)
        """
        try:
            # Format authors nicely
            author_str = ""
            if authors:
                if len(authors) == 1:
                    author_str = authors[0]
                elif len(authors) == 2:
                    author_str = f"{authors[0]} & {authors[1]}"
                else:
                    author_str = f"{authors[0]} et al."

            # Create message
            if author_str and year:
                message = f"{author_str} ({year}): {title[:50]}..."
            elif title:
                message = f"{title[:60]}..."
            else:
                message = "Found academic source"

            entry = {
                "id": f"source_{int(time.time() * 1000)}",
                "timestamp": datetime.now().isoformat(),
                "type": "found",
                "message": message,
                "icon": "📄",
                "source_data": {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "type": source_type
                }
            }

            self._activity_log.append(entry)

            if len(self._activity_log) > self.MAX_ACTIVITY_LOG_SIZE:
                self._activity_log = self._activity_log[-self.MAX_ACTIVITY_LOG_SIZE:]

            # Update DB
            self.supabase.table(self.table_name).update({
                "progress_details": {"activity_log": self._activity_log},
                "updated_at": datetime.now().isoformat()
            }).eq("id", self.record_id).execute()

        except Exception as e:
            logger.warning(f"Source log failed: {e}")

    def update_research(self, sources_count: int, phase_detail: str = ""):
        """Update research phase progress."""
        self.update_phase(
            phase="research",
            progress_percent=20,
            sources_count=sources_count,
            details={"phase_detail": phase_detail} if phase_detail else None
        )
    
    def update_writing(self, chapters_count: int, chapter_name: str = ""):
        """Update writing phase progress."""
        # Progress: 20% (research done) + 50% * (chapters / expected 6-8 chapters)
        progress = 20 + int(50 * min(chapters_count / 7, 1))
        
        self.update_phase(
            phase="writing",
            progress_percent=progress,
            chapters_count=chapters_count,
            details={"current_chapter": chapter_name} if chapter_name else None
        )
    
    def update_formatting(self):
        """Update formatting phase progress."""
        self.update_phase(
            phase="formatting",
            progress_percent=75,
            details={"stage": "formatting_and_citations"}
        )
    
    def update_exporting(self, export_type: str = ""):
        """Update export phase progress."""
        self.update_phase(
            phase="exporting",
            progress_percent=90,
            details={"export_type": export_type} if export_type else None
        )
    
    def mark_completed(self):
        """Mark draft as completed."""
        try:
            # Add completion activity entry
            self._add_activity_entry("completed", "generation_complete", {})

            # Build progress_details with activity_log
            progress_details = {
                "activity_log": self._activity_log,
                "stage": "completed"
            }

            update_data = {
                "status": "completed",  # Critical: frontend checks this field!
                "current_phase": "exporting",  # DB constraint only allows: research, structure, writing, compiling, exporting
                "progress_percent": 100,
                "progress_details": progress_details,
                "updated_at": datetime.now().isoformat()
            }

            self.supabase.table(self.table_name).update(update_data).eq("id", self.record_id).execute()
            logger.info("Generation completed successfully!")

        except Exception as e:
            logger.error(f"Failed to mark as completed: {e}")

    def mark_failed(self, error_message: str = None):
        """Mark draft as failed with optional error message."""
        try:
            # Log error to activity feed
            self._add_activity_entry("error", "generation_failed", {"error": error_message or "Unknown error"})

            update_data = {
                "status": "failed",
                "progress_details": {"activity_log": self._activity_log, "stage": "failed"},
                "updated_at": datetime.now().isoformat()
            }

            if error_message:
                update_data["error_message"] = error_message

            self.supabase.table(self.table_name).update(update_data).eq("id", self.record_id).execute()
            logger.error(f"Generation failed: {error_message or 'Unknown error'}")

        except Exception as e:
            logger.error(f"Failed to mark as failed: {e}")

